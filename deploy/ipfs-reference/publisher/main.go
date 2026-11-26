// Publish one operator-approved, versioned HLS tree using Kubo URLStore.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base32"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"net/url"
	"os"
	"path"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"time"
)

type publisher struct {
	client *http.Client
	origin string
	rpc    string
	token  string
}

func (p publisher) stream(ctx context.Context, m manifest, o object, dst io.Writer) error {
	hash := sha256.New()
	for start := int64(0); start < o.Size; {
		end := start + min(int64(blockSize), o.Size-start) - 1
		req, err := http.NewRequestWithContext(ctx, "GET", p.origin+referencePath(m, o), nil)
		if err != nil {
			return err
		}
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-%d", start, end))
		response, err := p.client.Do(req)
		if err != nil {
			return fmt.Errorf("read reference: %w", err)
		}
		if response.StatusCode == http.StatusTooManyRequests {
			response.Body.Close()
			seconds, err := strconv.Atoi(response.Header.Get("Retry-After"))
			if err != nil || seconds < 1 || seconds > 3600 {
				return errors.New("origin rate-limited the read without a valid retry interval")
			}
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(time.Duration(seconds) * time.Second):
				continue
			}
		}
		expected := fmt.Sprintf("bytes %d-%d/%d", start, end, o.Size)
		length := end - start + 1
		if response.StatusCode != http.StatusPartialContent || response.Header.Get("Content-Range") != expected ||
			response.ContentLength != length {
			response.Body.Close()
			return fmt.Errorf("origin refused the approved range or returned inconsistent metadata (HTTP %d)", response.StatusCode)
		}
		n, err := io.CopyN(io.MultiWriter(dst, hash), response.Body, length)
		response.Body.Close()
		if err != nil || n != length {
			return errors.New("incomplete source range")
		}
		start = end + 1
	}
	if !digestMatches(o.Hash, hash.Sum(nil)) {
		return errors.New("source digest differs from approval")
	}
	return nil
}

func (p publisher) rpcRequest(ctx context.Context, command string, body io.Reader, contentType string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, "POST", p.rpc+"/api/v0/"+command, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+p.token)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	resp, err := p.client.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		return nil, fmt.Errorf("Kubo RPC returned HTTP %d", resp.StatusCode)
	}
	return resp, nil
}

func (p publisher) writeTree(ctx context.Context, m manifest, files map[string]object, form *multipart.Writer) error {
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		o := files[name]
		header := make(textproto.MIMEHeader)
		header.Set("Content-Disposition", fmt.Sprintf(`form-data; name="file"; filename="%s"`, name))
		header.Set("Content-Type", "application/octet-stream")
		header.Set("Abspath", p.origin+referencePath(m, o))
		part, err := form.CreatePart(header)
		if err != nil {
			return err
		}
		if err := p.stream(ctx, m, o, part); err != nil {
			return err
		}
	}
	return form.Close()
}

func directoryCID(cid string) bool {
	// add requests CIDv1. A wrapped UnixFS directory uses dag-pb and SHA-256.
	if len(cid) != 59 || cid[0] != 'b' || strings.ToLower(cid) != cid {
		return false
	}
	raw, err := base32.StdEncoding.WithPadding(base32.NoPadding).DecodeString(strings.ToUpper(cid[1:]))
	return err == nil && len(raw) == 36 && bytes.Equal(raw[:4], []byte{1, 0x70, 0x12, 0x20})
}

func (p publisher) stage(ctx context.Context, m manifest, files map[string]object) (string, error) {
	reader, writer := io.Pipe()
	form := multipart.NewWriter(writer)
	result := make(chan error, 1)
	go func() {
		err := p.writeTree(ctx, m, files, form)
		writer.CloseWithError(err)
		result <- err
	}()
	const add = "add?nocopy=true&pin=false&cid-version=1&raw-leaves=true&recursive=true&wrap-with-directory=true&progress=false"
	resp, err := p.rpcRequest(ctx, add, reader, form.FormDataContentType())
	if err != nil {
		reader.Close()
		<-result
		return "", err
	}
	// The daemon can stream result rows while the request is still being
	// written. Drain both directions before committing the pin.
	root, parseErr := readAddResult(resp, files)
	resp.Body.Close()
	reader.Close()
	if streamErr := <-result; streamErr != nil {
		return "", streamErr
	}
	return root, parseErr
}

func readAddResult(resp *http.Response, files map[string]object) (string, error) {
	decoder := json.NewDecoder(resp.Body)
	root := ""
	seen := make(map[string]bool, len(files))
	dirs := make(map[string]bool)
	for name := range files {
		for dir := path.Dir(name); dir != "."; dir = path.Dir(dir) {
			dirs[dir] = true
		}
	}
	for {
		var row struct{ Name, Hash, Message string }
		err := decoder.Decode(&row)
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil || row.Message != "" || row.Hash == "" || root != "" {
			return "", errors.New("invalid or incomplete Kubo add response")
		}
		if row.Name == "" {
			root = row.Hash
		} else if _, ok := files[row.Name]; ok {
			if seen[row.Name] {
				return "", errors.New("duplicate file in Kubo add response")
			}
			seen[row.Name] = true
		} else if !dirs[row.Name] {
			return "", errors.New("Kubo returned an unexpected directory entry")
		}
	}
	if resp.Trailer.Get("X-Stream-Error") != "" || !directoryCID(root) || len(seen) != len(files) {
		return "", errors.New("Kubo did not finish the approved directory")
	}
	return root, nil
}

func (p publisher) publish(ctx context.Context, filename string) (string, error) {
	m, files, err := readApproval(filename)
	if err != nil {
		return "", err
	}
	err = verifyPlaybackTree(files, func(o object) ([]byte, error) {
		var buf bytes.Buffer
		err := p.stream(ctx, m, o, &buf)
		return buf.Bytes(), err
	})
	if err != nil {
		return "", err
	}
	root, err := p.stage(ctx, m, files)
	if err != nil {
		return "", err
	}
	// Adding can take minutes. Re-read both the approval and the authorized
	// master before changing the set of recursively pinned roots.
	current, _, err := readApproval(filename)
	if err != nil || !reflect.DeepEqual(m, current) {
		return "", errors.New("approval changed during add")
	}
	if err := p.stream(ctx, m, files["master.m3u8"], io.Discard); err != nil {
		return "", err
	}
	resp, err := p.rpcRequest(ctx, "pin/add?recursive=true&arg="+url.QueryEscape(root), nil, "")
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 65537))
	var pinned struct{ Pins []string }
	if err != nil || len(raw) > 65536 || json.Unmarshal(raw, &pinned) != nil ||
		resp.Trailer.Get("X-Stream-Error") != "" || len(pinned.Pins) != 1 || pinned.Pins[0] != root {
		return "", errors.New("no recursive pin confirmation for the approved root")
	}
	return root, nil
}

func run() error {
	approval := flag.String("manifest", "", "path to the single approved UUID.json file")
	tokenFile := flag.String("rpc-token-file", "", "private file containing the Kubo bearer token")
	rpcPort := flag.Int("rpc-port", 5181, "loopback Kubo RPC port")
	originPort := flag.Int("origin-port", 8785, "loopback S3 reference origin port")
	timeout := flag.Duration("timeout", 2*time.Hour, "overall publication deadline")
	flag.Parse()
	if *approval == "" || *tokenFile == "" || flag.NArg() != 0 || *timeout <= 0 ||
		*rpcPort < 1 || *rpcPort > 65535 || *originPort < 1 || *originPort > 65535 || *rpcPort == *originPort {
		return errors.New("provide a manifest, a token file and distinct valid loopback ports")
	}
	info, err := os.Lstat(*tokenFile)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 4096 {
		return errors.New("RPC token must be a private regular file")
	}
	credential, err := os.ReadFile(*tokenFile)
	if err != nil {
		return err
	}
	token := strings.TrimSpace(string(credential))
	if token == "" || strings.ContainsAny(token, " \r\n\t") {
		return errors.New("invalid RPC token")
	}
	ctx, cancel := context.WithTimeout(context.Background(), *timeout)
	defer cancel()
	p := publisher{
		client: &http.Client{Transport: &http.Transport{Proxy: nil, DisableCompression: true,
			ResponseHeaderTimeout: *timeout, IdleConnTimeout: 30 * time.Second},
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }},
		origin: "http://127.0.0.1:" + strconv.Itoa(*originPort),
		rpc:    "http://127.0.0.1:" + strconv.Itoa(*rpcPort), token: token,
	}
	root, err := p.publish(ctx, *approval)
	if err == nil {
		fmt.Println(root)
	}
	return err
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
