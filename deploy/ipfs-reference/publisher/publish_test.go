package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"testing"
)

const testVideo = "03582a98-1cbc-4be3-a4b2-31292003d261"
const testRoot = "bafybeidosoqui4j57nlswzl3whsrjyc2xsytn7hmmybawofr3hv6fsggie"

func sample(t *testing.T) (string, manifest, map[string][]byte) {
	t.Helper()
	prefix := "operator-readiness/ipfs-reference/" + testVideo + "/"
	m := manifest{Schema: 1, Video: testVideo, Master: prefix + "master.m3u8"}
	files := map[string][]byte{
		"master.m3u8":  []byte("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000\nv/index.m3u8\n"),
		"v/index.m3u8": []byte("#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:2,\nseg.m4s\n#EXT-X-ENDLIST\n"),
		"v/init.mp4":   []byte("init"),
		"v/seg.m4s":    bytes.Repeat([]byte{0x2a}, blockSize+7),
	}
	bodies := map[string][]byte{}
	for name, data := range files {
		o := object{Key: prefix + name, Version: "source-version-1", Size: int64(len(data)), Hash: fmt.Sprintf("%x", sha256.Sum256(data))}
		o.ID = objectID(m, o)
		m.Objects = append(m.Objects, o)
		bodies[o.ID] = data
	}
	filename := filepath.Join(t.TempDir(), testVideo+".json")
	raw, _ := json.Marshal(m)
	if err := os.WriteFile(filename, raw, 0600); err != nil {
		t.Fatal(err)
	}
	return filename, m, bodies
}

func TestPublishOnlyApprovedReferences(t *testing.T) {
	for _, failure := range []string{"", "source_changed", "origin_full_response", "trailer", "approval_withdrawn", "wrong_pin"} {
		t.Run(failure, func(t *testing.T) {
			filename, m, bodies := sample(t)
			origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				id, ok := strings.CutPrefix(r.URL.Path, "/v1/references/"+m.Video+"/")
				data := bodies[id]
				var start, end int
				n, err := fmt.Sscanf(r.Header.Get("Range"), "bytes=%d-%d", &start, &end)
				if !ok || len(data) == 0 || err != nil || n != 2 || start < 0 || end >= len(data) || end-start+1 > blockSize {
					http.Error(w, "range", 416)
					return
				}
				chunk := bytes.Clone(data[start : end+1])
				if failure == "source_changed" && len(data) > blockSize {
					chunk[0] ^= 1
				}
				w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, len(data)))
				w.Header().Set("Content-Length", strconv.Itoa(len(chunk)))
				if failure != "origin_full_response" {
					w.WriteHeader(206)
				}
				w.Write(chunk)
			}))
			defer origin.Close()
			pinCalls := 0
			rpc := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "Bearer test" || r.Method != "POST" {
					http.Error(w, "auth", 403)
					return
				}
				switch r.URL.Path {
				case "/api/v0/add":
					if r.URL.Query().Get("nocopy") != "true" || r.URL.Query().Get("pin") != "false" {
						t.Error("copy or implicit pin requested")
					}
					_, params, _ := mime.ParseMediaType(r.Header.Get("Content-Type"))
					reader := multipart.NewReader(r.Body, params["boundary"])
					var names []string
					for {
						part, err := reader.NextPart()
						if err == io.EOF {
							break
						}
						if err != nil {
							return
						}
						_, params, _ := mime.ParseMediaType(part.Header.Get("Content-Disposition"))
						name := params["filename"]
						ref := part.Header.Get("Abspath")
						id, ok := strings.CutPrefix(ref, origin.URL+"/v1/references/"+m.Video+"/")
						body, err := io.ReadAll(part)
						if err != nil {
							return
						}
						if !ok || !bytes.Equal(bodies[id], body) {
							t.Errorf("incorrect body or reference for %s", name)
						}
						names = append(names, name)
					}
					want := []string{"master.m3u8", "v/index.m3u8", "v/init.mp4", "v/seg.m4s"}
					sort.Strings(names)
					if !reflect.DeepEqual(names, want) {
						t.Error("missing approved file")
						return
					}
					w.Header().Set("Trailer", "X-Stream-Error")
					for _, name := range names {
						fmt.Fprintf(w, "{\"Name\":%q,\"Hash\":\"leaf\"}\n", name)
					}
					fmt.Fprintf(w, "{\"Name\":\"\",\"Hash\":%q}\n", testRoot)
					if failure == "trailer" {
						w.Header().Set("X-Stream-Error", "aborted")
					}
					if failure == "approval_withdrawn" {
						os.Remove(filename)
					}
				case "/api/v0/pin/add":
					pinCalls++
					root := testRoot
					if failure == "wrong_pin" {
						root = "wrong-root"
					}
					fmt.Fprintf(w, "{\"Pins\":[%q]}", root)
				default:
					http.NotFound(w, r)
				}
			}))
			defer rpc.Close()
			p := publisher{client: rpc.Client(), origin: origin.URL, rpc: rpc.URL, token: "test"}
			root, err := p.publish(context.Background(), filename)
			if failure == "" {
				if err != nil || root != testRoot || pinCalls != 1 {
					t.Fatalf("publish: %s, %v (%d pin calls)", root, err, pinCalls)
				}
			} else if err == nil || (failure != "wrong_pin" && pinCalls != 0) {
				t.Fatalf("unexpected pin result: %s, %v (%d pin calls)", root, err, pinCalls)
			}
		})
	}
}

func TestRejectSupplementaryAndExternalMedia(t *testing.T) {
	filename, _, bodies := sample(t)
	_, files, err := readApproval(filename)
	if err != nil {
		t.Fatal(err)
	}
	for _, reference := range []string{
		"https://elsewhere/clip.m3u8", "../other.mp4", "#EXT-X-KEY:METHOD=AES-128,URI=\"key\"",
		"#EXT-X-CONTENT-STEERING:SERVER-URI=\"https://elsewhere/steering\"\nv/index.m3u8",
		"#EXT-X-UNKNOWN:EXTERNAL=\"https://elsewhere/file\"\nv/index.m3u8",
	} {
		err := verifyPlaybackTree(files, func(o object) ([]byte, error) {
			if strings.HasSuffix(o.Key, "/master.m3u8") {
				return []byte("#EXTM3U\n" + reference), nil
			}
			return bodies[o.ID], nil
		})
		if err == nil {
			t.Fatalf("accepted %s", reference)
		}
	}
	files["download.mp4"] = object{}
	if verifyPlaybackTree(files, func(o object) ([]byte, error) { return bodies[o.ID], nil }) == nil {
		t.Fatal("accepted a file outside the playable HLS tree")
	}
}

func TestReadApprovalBindsObjectVersions(t *testing.T) {
	for _, mutation := range []string{"version", "key", "hash", "generation", "duplicate", "mode"} {
		t.Run(mutation, func(t *testing.T) {
			filename, m, _ := sample(t)
			switch mutation {
			case "version":
				m.Objects[0].Version = "replacement"
			case "key":
				m.Objects[0].Key = "other/private.mp4"
			case "hash":
				m.Objects[0].Hash = strings.Repeat("0", 64)
			case "generation":
				m.Master = "streaming-playlists/" + testVideo + "/master.m3u8"
			case "duplicate":
				m.Objects = append(m.Objects, m.Objects[0])
			case "mode":
				if err := os.Chmod(filename, 0666); err != nil {
					t.Fatal(err)
				}
			}
			raw, _ := json.Marshal(m)
			if err := os.WriteFile(filename, raw, 0600); err != nil {
				t.Fatal(err)
			}
			if _, _, err := readApproval(filename); err == nil {
				t.Fatal("invalid approval accepted")
			}
		})
	}
}
