package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path"
	"regexp"
	"strconv"
	"strings"
)

const blockSize = 256 << 10

var (
	uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	hashPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
	namePattern = regexp.MustCompile(`^[A-Za-z0-9._/-]+$`)
	pathPart    = regexp.MustCompile(`^[A-Za-z0-9_-][A-Za-z0-9._-]{0,254}$`)
	versionID   = regexp.MustCompile(`^[!-~]{1,512}$`)
	generation  = regexp.MustCompile(`^r[1-9][0-9]*$`)
	uriAttr     = regexp.MustCompile(`(?:[:,])URI="([^"]+)"`)
)

type object struct {
	ID      string `json:"id"`
	Key     string `json:"key"`
	Version string `json:"version_id"`
	Size    int64  `json:"size"`
	Hash    string `json:"sha256"`
}

type manifest struct {
	Schema  int      `json:"schema"`
	Video   string   `json:"video_id"`
	Master  string   `json:"master_key"`
	Objects []object `json:"objects"`
}

func objectID(m manifest, o object) string {
	fields := []string{m.Video, m.Master, o.Key, o.Version, strconv.FormatInt(o.Size, 10), o.Hash}
	return fmt.Sprintf("%x", sha256.Sum256([]byte(strings.Join(fields, "\x00"))))
}

func readApproval(filename string) (manifest, map[string]object, error) {
	var m manifest
	info, err := os.Lstat(filename)
	if err != nil {
		return m, nil, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0022 != 0 || info.Size() > 2<<20 {
		return m, nil, errors.New("approval must be a bounded, operator-controlled regular file")
	}
	raw, err := os.ReadFile(filename)
	if err != nil {
		return m, nil, err
	}
	if err := json.Unmarshal(raw, &m); err != nil {
		return m, nil, fmt.Errorf("invalid approval: %w", err)
	}
	parts := strings.Split(m.Master, "/")
	validMaster := len(parts) == 4 && parts[3] == "master.m3u8" &&
		((parts[0] == "streaming-playlists" && parts[1] == m.Video && generation.MatchString(parts[2])) ||
			(parts[0] == "operator-readiness" && parts[1] == "ipfs-reference" && parts[2] == m.Video))
	if m.Schema != 1 || !uuidPattern.MatchString(m.Video) || path.Base(filename) != m.Video+".json" || !validMaster {
		return m, nil, errors.New("approval must identify one video and its exact HLS master")
	}
	if len(m.Objects) == 0 || len(m.Objects) > 4096 {
		return m, nil, errors.New("invalid number of approved objects")
	}
	prefix := path.Dir(m.Master) + "/"
	files := make(map[string]object, len(m.Objects))
	for _, o := range m.Objects {
		name, ok := strings.CutPrefix(o.Key, prefix)
		if !ok || len(o.Key) > 1024 {
			return m, nil, errors.New("object outside the approved generation")
		}
		for _, part := range strings.Split(name, "/") {
			if !pathPart.MatchString(part) {
				return m, nil, errors.New("invalid object path segment")
			}
		}
		if _, exists := files[name]; exists || !versionID.MatchString(o.Version) || strings.EqualFold(o.Version, "null") ||
			o.Size < 1 || o.Size > 5<<40 || !hashPattern.MatchString(o.Hash) || o.ID != objectID(m, o) {
			return m, nil, errors.New("invalid, duplicate or unversioned reference")
		}
		files[name] = o
	}
	if _, ok := files["master.m3u8"]; !ok {
		return m, nil, errors.New("approved master missing")
	}
	return m, files, nil
}

// Fetch playlists before sending anything to Kubo. A directory listing can
// include progressive downloads and originals that HLS viewers never request.
func verifyPlaybackTree(files map[string]object, playlist func(object) ([]byte, error)) error {
	seen := map[string]bool{}
	children := map[string][]string{}
	mediaPlaylists := 0
	pending := []string{"master.m3u8"}
	for len(pending) > 0 {
		name := pending[len(pending)-1]
		pending = pending[:len(pending)-1]
		if seen[name] {
			continue
		}
		entry, ok := files[name]
		if !ok {
			return errors.New("playlist references an unapproved object")
		}
		seen[name] = true
		if path.Ext(name) != ".m3u8" {
			switch path.Ext(name) {
			case ".mp4", ".m4s", ".m4a", ".ts", ".aac", ".vtt":
			default:
				return errors.New("unrecognized HLS payload")
			}
			continue
		}
		if entry.Size > 2<<20 {
			return errors.New("playlist exceeds verification limit")
		}
		body, err := playlist(entry)
		if err != nil {
			return err
		}
		lines := strings.Split(strings.ReplaceAll(string(body), "\r\n", "\n"), "\n")
		if len(lines) < 2 || lines[0] != "#EXTM3U" {
			return errors.New("invalid HLS playlist")
		}
		var refs []string
		var media, endList bool
		for _, line := range lines[1:] {
			line = strings.TrimSpace(line)
			switch {
			case line == "":
			case strings.HasPrefix(line, "#EXTINF:"):
				media = true
			case line == "#EXT-X-ENDLIST":
				endList = true
			case strings.HasPrefix(line, "#EXT-X-KEY:"), strings.HasPrefix(line, "#EXT-X-SESSION-KEY:"),
				strings.HasPrefix(line, "#EXT-X-DEFINE:"), strings.HasPrefix(line, "#EXT-X-CONTENT-STEERING:"):
				return errors.New("encrypted or externally configured HLS is ineligible")
			case strings.HasPrefix(line, "#EXT"):
				for _, match := range uriAttr.FindAllStringSubmatch(line, -1) {
					refs = append(refs, match[1])
				}
			case !strings.HasPrefix(line, "#"):
				refs = append(refs, line)
			}
		}
		if len(refs) == 0 || (media && !endList) {
			return errors.New("empty or unfinished HLS playlist")
		}
		if media {
			mediaPlaylists++
		}
		for _, ref := range refs {
			if !namePattern.MatchString(ref) || strings.HasPrefix(ref, "/") {
				return errors.New("HLS reference must be a relative playback path")
			}
			target := path.Join(path.Dir(name), ref)
			if target == ".." || strings.HasPrefix(target, "../") {
				return errors.New("HLS reference leaves the generation")
			}
			if path.Ext(target) == ".m3u8" {
				children[name] = append(children[name], target)
			}
			pending = append(pending, target)
		}
	}
	if len(seen) != len(files) {
		return errors.New("approval includes files outside the playback tree")
	}
	if mediaPlaylists == 0 || hasPlaylistCycle("master.m3u8", children, map[string]byte{}) {
		return errors.New("HLS tree must lead to a completed media playlist")
	}
	return nil
}

func hasPlaylistCycle(name string, children map[string][]string, visited map[string]byte) bool {
	switch visited[name] {
	case 1:
		return true
	case 2:
		return false
	}
	visited[name] = 1
	for _, child := range children[name] {
		if hasPlaylistCycle(child, children, visited) {
			return true
		}
	}
	visited[name] = 2
	return false
}

func referencePath(m manifest, o object) string {
	return "/v1/references/" + url.PathEscape(m.Video) + "/" + url.PathEscape(o.ID)
}

func digestMatches(expected string, digest []byte) bool {
	return hex.EncodeToString(digest) == expected
}
