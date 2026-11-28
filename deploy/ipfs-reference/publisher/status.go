package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"maps"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"
)

const maxStatusApprovals = 64
const statusSampleBytes int64 = 8192
const statusByteBudget int64 = 4 << 20

type statusSource struct {
	Approvals        string `json:"approvals"`
	Journal          string `json:"journal"`
	OriginPort       int    `json:"origin_port"`
	AllowUnpublished bool   `json:"allow_unpublished,omitempty"`
}

type statusConfig struct {
	RPCPort     int            `json:"rpc_port"`
	GatewayPort int            `json:"gateway_port"`
	TokenFile   string         `json:"token_file"`
	Sources     []statusSource `json:"sources"`
}

type referenceStatus struct {
	Version    int    `json:"version"`
	ObservedAt string `json:"observed_at"`
	State      string `json:"state"`
	Reason     string `json:"reason"`
	Pinned     *int   `json:"pinned,omitempty"`
}

func statusValue(reason string, n *int) referenceStatus {
	state := "degraded"
	switch reason {
	case "verified":
		state = "ok"
	case "approval_unavailable", "node_unavailable":
		state = "down"
	}
	return referenceStatus{1, time.Now().UTC().Format(time.RFC3339Nano), state, reason, n}
}

type approvedProbe struct {
	root, video, approval string
	origin                int
	files                 map[string]object
}

// Read the operator's installed approvals as well as the publisher's journal. Reading an empty journal alone misses an unpublished approval.
func statusApprovals(sources []statusSource) ([]approvedProbe, string) {
	var out []approvedProbe
	metadataBudget := int64(8 << 20)
	for _, source := range sources {
		dir, err := os.Open(source.Approvals)
		if err != nil {
			return nil, "approval_unavailable"
		}
		entries, err := dir.ReadDir(maxStatusApprovals + 2)
		dir.Close()
		if err != nil && !errors.Is(err, io.EOF) {
			return nil, "approval_unavailable"
		}
		if len(entries) > maxStatusApprovals+1 {
			return nil, "media_unverified"
		}
		sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
		j := journal{Items: make(map[string]receipt)}
		if err := readJournal(source.Journal, &j); err != nil && !(errors.Is(err, os.ErrNotExist) && source.AllowUnpublished) {
			return nil, "approval_unavailable"
		}
		if len(j.Watch) > 0 {
			return nil, "pin_set_mismatch"
		}
		for _, entry := range entries {
			name := entry.Name()
			if strings.HasPrefix(name, ".") || !strings.HasSuffix(name, ".json") {
				continue
			}
			info, err := entry.Info()
			if err != nil {
				return nil, "approval_unavailable"
			}
			if info.Size() > metadataBudget {
				return nil, "media_unverified"
			}
			metadataBudget -= info.Size()
			m, files, err := readApproval(filepath.Join(source.Approvals, name))
			if err != nil {
				return nil, "approval_unavailable"
			}
			r, ok := j.Items[m.Video]
			if !ok || r.State != "pinned" || r.Approval != approvalHash(m) {
				return nil, "pin_set_mismatch"
			}
			out = append(out, approvedProbe{r.Root, m.Video, r.Approval, source.OriginPort, files})
			delete(j.Items, m.Video)
			if len(out) > maxStatusApprovals {
				return nil, "media_unverified"
			}
		}
		// A retained receipt after withdrawal is an unfinished reconciliation, even if Kubo no longer has the pin.
		if len(j.Items) > 0 {
			return nil, "pin_set_mismatch"
		}
	}
	return out, ""
}

func local(port int) string { return "http://127.0.0.1:" + strconv.Itoa(port) }

func (p publisher) probeBytes(ctx context.Context, address string, size, count int64, ranged bool) ([]byte, int, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, address, nil)
	if err != nil {
		return nil, 0, err
	}
	if ranged {
		request.Header.Set("Range", fmt.Sprintf("bytes=0-%d", count-1))
	}
	res, err := p.client.Do(request)
	if err != nil {
		return nil, 0, err
	}
	defer res.Body.Close()
	full := res.StatusCode == http.StatusOK && size == count
	partial := ranged && res.StatusCode == http.StatusPartialContent && res.Header.Get("Content-Range") == fmt.Sprintf("bytes 0-%d/%d", count-1, size)
	if (!full && !partial) || (res.ContentLength >= 0 && res.ContentLength != count) {
		return nil, res.StatusCode, errors.New("inconsistent media response")
	}
	b, err := io.ReadAll(io.LimitReader(res.Body, count+1))
	if err != nil || int64(len(b)) != count || res.Trailer.Get("X-Stream-Error") != "" {
		return nil, res.StatusCode, errors.New("incomplete media response")
	}
	return b, res.StatusCode, nil
}

// Follow the first ordinary variant to a segment URI after EXTINF, excluding
// EXT-X-MAP initializers and entries belonging only to subtitles or alternate renditions.
func (p publisher) mediaSample(ctx context.Context, prefix string, files map[string]object, budget *int64) (object, string, bool) {
	name := "master.m3u8"
	for depth := 0; depth < 8; depth++ {
		entry, ok := files[name]
		if !ok || entry.Size > 256<<10 || entry.Size > *budget {
			break
		}
		*budget -= entry.Size
		raw, _, err := p.probeBytes(ctx, prefix+name, entry.Size, entry.Size, false)
		if err != nil || fmt.Sprintf("%x", sha256.Sum256(raw)) != entry.Hash {
			break
		}
		lines := strings.Split(strings.ReplaceAll(string(raw), "\r\n", "\n"), "\n")
		if len(lines) == 0 || lines[0] != "#EXTM3U" {
			break
		}
		kind, next := "", ""
		for _, line := range lines[1:] {
			line = strings.TrimSpace(line)
			switch {
			case strings.HasPrefix(line, "#EXTINF:"):
				kind = "segment"
			case strings.HasPrefix(line, "#EXT-X-STREAM-INF:"):
				kind = "variant"
			case kind != "" && line != "" && !strings.HasPrefix(line, "#"):
				if !namePattern.MatchString(line) || strings.HasPrefix(line, "/") {
					return object{}, "", false
				}
				next = path.Join(path.Dir(name), line)
			}
			if next != "" {
				break
			}
		}
		if next == "" {
			break
		}
		if kind == "segment" {
			o, ok := files[next]
			switch path.Ext(next) {
			case ".m4s", ".mp4", ".m4a", ".ts", ".aac":
				return o, next, ok
			}
			break
		}
		if path.Ext(next) != ".m3u8" {
			break
		}
		name = next
	}
	return object{}, "", false
}

func (p publisher) verifySample(ctx context.Context, gateway int, a approvedProbe, budget *int64) string {
	master := a.files["master.m3u8"]
	if strings.HasPrefix(master.Key, "streaming-playlists/") {
		// Evaluate live catalogue policy before reading a possibly cached gateway playlist.
		req, err := http.NewRequestWithContext(ctx, http.MethodHead, local(a.origin)+referencePath(manifest{Video: a.video}, master), nil)
		if err != nil {
			return "approval_unavailable"
		}
		res, err := p.client.Do(req)
		if err != nil {
			return "approval_unavailable"
		}
		res.Body.Close()
		switch res.StatusCode {
		case http.StatusForbidden, http.StatusNotFound, http.StatusGone:
			return "pin_set_mismatch"
		case http.StatusOK:
			if res.ContentLength != master.Size {
				return "media_unverified"
			}
		default:
			return "approval_unavailable"
		}
	}
	prefix := local(gateway) + "/ipfs/" + a.root + "/"
	media, name, ok := p.mediaSample(ctx, prefix, a.files, budget)
	if !ok {
		return "media_unverified"
	}
	sample := min(media.Size, statusSampleBytes)
	if sample*2 > *budget {
		return "media_unverified"
	}
	*budget -= sample * 2
	// The origin rechecks native generation eligibility for the exact immutable object.
	origin, status, err := p.probeBytes(ctx, local(a.origin)+referencePath(manifest{Video: a.video}, media), media.Size, sample, true)
	if err != nil {
		if status == 403 || status == 404 || status == 410 {
			return "pin_set_mismatch"
		}
		if strings.HasPrefix(media.Key, "streaming-playlists/") {
			return "approval_unavailable"
		}
		return "media_unverified"
	}
	body, _, err := p.probeBytes(ctx, prefix+name, media.Size, sample, true)
	if err != nil || !bytes.Equal(body, origin) || (sample == media.Size && fmt.Sprintf("%x", sha256.Sum256(body)) != media.Hash) {
		return "media_unverified"
	}
	return ""
}

func (p publisher) statusPins(ctx context.Context, wanted map[string]struct{}) string {
	recursive, err := p.pinSet(ctx, "recursive")
	if err != nil {
		return "node_unavailable"
	}
	direct, err := p.pinSet(ctx, "direct")
	if err != nil {
		return "node_unavailable"
	}
	if len(direct) != 0 || !maps.Equal(recursive, wanted) {
		return "pin_set_mismatch"
	}
	return ""
}

func (p publisher) collectStatus(ctx context.Context, c statusConfig) referenceStatus {
	approvals, reason := statusApprovals(c.Sources)
	if reason != "" {
		return statusValue(reason, nil)
	}
	roots := map[string]struct{}{}
	for _, a := range approvals {
		roots[a.root] = struct{}{}
	}
	if reason = p.statusPins(ctx, roots); reason != "" {
		return statusValue(reason, nil)
	}
	budget := statusByteBudget
	for _, a := range approvals {
		if reason = p.verifySample(ctx, c.GatewayPort, a, &budget); reason != "" {
			return statusValue(reason, nil)
		}
	}
	// Publication and withdrawal are concurrent. A changed approval or pin inventory invalidates this observation.
	after, reason := statusApprovals(c.Sources)
	if reason != "" {
		return statusValue(reason, nil)
	}
	if !slices.EqualFunc(after, approvals, func(a, b approvedProbe) bool {
		return a.video == b.video && a.origin == b.origin && a.approval == b.approval && a.root == b.root
	}) {
		return statusValue("pin_set_mismatch", nil)
	}
	if reason = p.statusPins(ctx, roots); reason != "" {
		return statusValue(reason, nil)
	}
	n := len(roots)
	return statusValue("verified", &n)
}

func writeStatus(filename string, value referenceStatus) error {
	dir := filepath.Dir(filename)
	tmp, err := os.CreateTemp(dir, ".reference-status-")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	err = json.NewEncoder(tmp).Encode(value)
	if err == nil {
		err = tmp.Chmod(0644)
	}
	if err == nil {
		err = tmp.Sync()
	}
	if e := tmp.Close(); err == nil {
		err = e
	}
	if err != nil {
		return err
	}
	if err = os.Rename(tmp.Name(), filename); err != nil {
		return err
	}
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}

func loadProbeConfig(filename string) (statusConfig, publisher, string) {
	file, err := os.Open(filename)
	if err != nil {
		return statusConfig{}, publisher{}, "approval_unavailable"
	}
	defer file.Close()
	raw, err := io.ReadAll(io.LimitReader(file, 16385))
	var c statusConfig
	if err != nil || len(raw) > 16384 || json.Unmarshal(raw, &c) != nil || len(c.Sources) == 0 || len(c.Sources) > 8 {
		return statusConfig{}, publisher{}, "approval_unavailable"
	}
	validPort := func(port int) bool { return port > 0 && port <= 65535 }
	if !validPort(c.RPCPort) || !validPort(c.GatewayPort) || c.RPCPort == c.GatewayPort || !filepath.IsAbs(c.TokenFile) {
		return statusConfig{}, publisher{}, "approval_unavailable"
	}
	for _, s := range c.Sources {
		if !validPort(s.OriginPort) || s.OriginPort == c.RPCPort || s.OriginPort == c.GatewayPort || !filepath.IsAbs(s.Approvals) || !filepath.IsAbs(s.Journal) {
			return statusConfig{}, publisher{}, "approval_unavailable"
		}
	}
	info, err := os.Lstat(c.TokenFile)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 4096 {
		return statusConfig{}, publisher{}, "node_unavailable"
	}
	b, err := os.ReadFile(c.TokenFile)
	token := strings.TrimSpace(string(b))
	if err != nil || token == "" || strings.ContainsAny(token, " \r\n\t") {
		return statusConfig{}, publisher{}, "node_unavailable"
	}
	p := publisher{rpc: local(c.RPCPort), token: token, client: &http.Client{Transport: &http.Transport{Proxy: nil, DisableCompression: true, ResponseHeaderTimeout: 5 * time.Second}, Timeout: 8 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
	return c, p, ""
}

func configuredStatus(ctx context.Context, filename string) referenceStatus {
	c, p, reason := loadProbeConfig(filename)
	if reason != "" {
		return statusValue(reason, nil)
	}
	return p.collectStatus(ctx, c)
}

func runStatus(args []string) error {
	f := flag.NewFlagSet("status", flag.ContinueOnError)
	config := f.String("config", "", "private reporter configuration")
	output := f.String("output", "", "aggregate JSON output file")
	if err := f.Parse(args); err != nil {
		return err
	}
	if f.NArg() != 0 || !filepath.IsAbs(*config) || !filepath.IsAbs(*output) {
		return errors.New("provide absolute status configuration and output paths")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Second)
	defer cancel()
	return writeStatus(*output, configuredStatus(ctx, *config))
}
