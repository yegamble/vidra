// The API reaches this reader on a Unix socket. Kubo and S3 addresses never
// come from a viewer, and a publisher receipt alone cannot authorize playback.
package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type watchBridge struct {
	config statusConfig
	node   publisher
}

type watchFile struct {
	root     string
	approval string
	file     object
}

// Resolve from the installed manifest on each request so withdrawal and atomic
// replacement take effect even for playlists that Kubo still has in memory.
func (b watchBridge) resolve(video, revision, name string) (watchFile, int) {
	for _, source := range b.config.Sources {
		m, files, err := readApproval(filepath.Join(source.Approvals, video+".json"))
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return watchFile{}, http.StatusServiceUnavailable
		}
		if m.Master != "streaming-playlists/"+video+"/"+revision+"/master.m3u8" {
			continue
		}
		file, ok := files[name]
		if !ok {
			return watchFile{}, http.StatusNotFound
		}
		var j journal
		err = readJournal(source.Journal, &j)
		if errors.Is(err, os.ErrNotExist) && source.AllowUnpublished {
			return watchFile{}, http.StatusNotFound
		}
		if err != nil {
			return watchFile{}, http.StatusServiceUnavailable
		}
		r, ok := j.Items[video]
		if !ok || r.State != "pinned" || r.Approval != approvalHash(m) || len(j.Watch[video]) != 0 {
			return watchFile{}, http.StatusNotFound
		}
		return watchFile{r.Root, r.Approval, file}, http.StatusOK
	}
	return watchFile{}, http.StatusNotFound
}

var watchTypes = map[string]string{
	".m3u8": "application/vnd.apple.mpegurl", ".m4s": "video/iso.segment", ".mp4": "video/mp4",
	".m4a": "audio/mp4", ".ts": "video/mp2t", ".aac": "audio/aac", ".vtt": "text/vtt",
}

// Resolve a single ordinary HTTP byte range against the size in the approved
// immutable manifest. One range covers HLS byte-range playlists and seeking.
func watchRange(header string, size int64) (first, last int64, valid bool) {
	if header == "" {
		return 0, size - 1, true
	}
	value, ok := strings.CutPrefix(header, "bytes=")
	left, right, dash := strings.Cut(value, "-")
	if !ok || !dash || (left == "" && right == "") {
		return 0, 0, false
	}
	number := func(s string) (int64, bool) {
		if s == "" || strings.Trim(s, "0123456789") != "" {
			return 0, false
		}
		n, err := strconv.ParseInt(s, 10, 64)
		return n, err == nil
	}
	if left == "" {
		n, ok := number(right)
		return size - min(n, size), size - 1, ok && n > 0
	}
	start, ok := number(left)
	if !ok || start >= size {
		return 0, 0, false
	}
	if right == "" {
		return start, size - 1, true
	}
	end, ok := number(right)
	return start, min(end, size-1), ok && end >= start
}

func (b watchBridge) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "private, no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	const prefix = "/api/v1/videos/"
	relative, ok := strings.CutPrefix(r.URL.Path, prefix)
	parts := strings.SplitN(relative, "/", 4)
	if !ok || len(parts) != 4 || !uuidPattern.MatchString(parts[0]) || parts[1] != "ipfs-reference" ||
		!generation.MatchString(parts[2]) || len(relative) > 1200 || r.URL.RawQuery != "" || r.URL.ForceQuery ||
		r.URL.EscapedPath() != r.URL.Path {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	video, rev, name := parts[0], parts[2], parts[3]
	for _, part := range strings.Split(name, "/") {
		if !pathPart.MatchString(part) {
			w.WriteHeader(http.StatusNotFound)
			return
		}
	}
	mediaType := watchTypes[path.Ext(name)]
	if mediaType == "" {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	target, code := b.resolve(video, rev, name)
	if code != http.StatusOK {
		w.WriteHeader(code)
		return
	}
	rangeHeader := r.Header.Get("Range")
	first, last, valid := watchRange(rangeHeader, target.file.Size)
	if !valid || len(r.Header.Values("Range")) > 1 {
		w.Header().Set("Content-Range", fmt.Sprintf("bytes */%d", target.file.Size))
		w.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
		return
	}
	pinned, err := b.node.recursivePin(r.Context(), target.root)
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}
	if !pinned {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	gateway := local(b.config.GatewayPort) + "/ipfs/" + target.root + "/" + name
	req, err := http.NewRequestWithContext(r.Context(), r.Method, gateway, nil)
	if err != nil {
		w.WriteHeader(http.StatusBadGateway)
		return
	}
	wantStatus := http.StatusOK
	if rangeHeader != "" {
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-%d", first, last))
		wantStatus = http.StatusPartialContent
	}
	response, err := b.node.client.Do(req)
	if err != nil {
		w.WriteHeader(http.StatusServiceUnavailable)
		return
	}
	defer response.Body.Close()
	size := last - first + 1
	contentRange := fmt.Sprintf("bytes %d-%d/%d", first, last, target.file.Size)
	if response.StatusCode != wantStatus || response.ContentLength != size ||
		response.Header.Get("Content-Encoding") != "" ||
		(wantStatus == http.StatusPartialContent && response.Header.Get("Content-Range") != contentRange) {
		w.WriteHeader(http.StatusBadGateway)
		return
	}
	// Gateway headers may arrive after the operator has withdrawn this file.
	current, code := b.resolve(video, rev, name)
	if code != http.StatusOK {
		w.WriteHeader(code)
		return
	}
	if current != target {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", mediaType)
	w.Header().Set("Content-Length", strconv.FormatInt(size, 10))
	w.Header().Set("Accept-Ranges", "bytes")
	if wantStatus == http.StatusPartialContent {
		w.Header().Set("Content-Range", contentRange)
	}
	w.WriteHeader(wantStatus)
	if r.Method == http.MethodGet {
		if _, err := io.CopyN(w, response.Body, size); err != nil {
			panic(http.ErrAbortHandler)
		}
	}
}

func runPlayback(args []string) error {
	flags := flag.NewFlagSet("serve-playback", flag.ContinueOnError)
	config := flags.String("config", "", "reference node configuration with pin/ls-only token")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 || !filepath.IsAbs(*config) {
		return errors.New("provide an absolute reference configuration path")
	}
	c, node, reason := loadProbeConfig(*config)
	if reason != "" {
		return fmt.Errorf("reference configuration: %s", reason)
	}
	if os.Getenv("LISTEN_PID") != strconv.Itoa(os.Getpid()) || os.Getenv("LISTEN_FDS") != "1" {
		return errors.New("one systemd Unix listening socket is required")
	}
	fd := os.NewFile(3, "reference-playback")
	if fd == nil {
		return errors.New("missing playback socket")
	}
	listener, err := net.FileListener(fd)
	fd.Close()
	if err != nil {
		return err
	}
	defer listener.Close()
	if listener.Addr().Network() != "unix" {
		return errors.New("playback requires a Unix listener")
	}
	// A segment may be larger than the status probe's eight-second sample.
	node.client.Timeout = 2 * time.Minute
	server := http.Server{Handler: watchBridge{c, node}, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 15 * time.Second,
		WriteTimeout: 2 * time.Minute, MaxHeaderBytes: 16 << 10}
	return server.Serve(listener)
}
