package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestReferenceStatusObservesOnlyApprovedPlayableRoots(t *testing.T) {
	cases := map[string]string{"healthy": "verified", "zero": "verified", "stray": "pin_set_mismatch", "stray_direct": "pin_set_mismatch", "pin_missing": "pin_set_mismatch", "pending": "pin_set_mismatch", "journal_missing": "approval_unavailable", "optional_unpublished_empty": "verified", "optional_unpublished_active": "pin_set_mismatch", "uncertain_withdrawal": "pin_set_mismatch", "changed_manifest": "pin_set_mismatch", "revoked_during_read": "pin_set_mismatch", "native_healthy": "verified", "native_denied": "pin_set_mismatch", "native_uncertain": "approval_unavailable", "unreadable_manifest": "approval_unavailable", "approval_directory_missing": "approval_unavailable", "rpc_down": "node_unavailable", "incomplete_rpc": "node_unavailable", "corrupt_gateway_media": "media_unverified", "corrupt_playlist": "media_unverified", "short_range": "media_unverified"}
	for run, want := range cases {
		t.Run(run, func(t *testing.T) {
			filename, m, bodies := sample(t)
			if strings.HasPrefix(run, "native_") {
				oldPrefix := strings.TrimSuffix(m.Master, "master.m3u8")
				newPrefix := "streaming-playlists/" + m.Video + "/r7/"
				m.Master = newPrefix + "master.m3u8"
				for i := range m.Objects {
					o := &m.Objects[i]
					data := bodies[o.ID]
					o.Key = newPrefix + strings.TrimPrefix(o.Key, oldPrefix)
					o.ID = objectID(m, *o)
					bodies[o.ID] = data
				}
				raw, _ := json.Marshal(m)
				if err := os.WriteFile(filename, raw, 0600); err != nil {
					t.Fatal(err)
				}
			}
			state := filepath.Join(t.TempDir(), "publications.json")
			r := receipt{Root: testRoot, Approval: approvalHash(m), State: "pinned", Owned: true}
			if run == "pending" {
				r.State = "pending"
			}
			if run == "changed_manifest" {
				r.Approval = strings.Repeat("e", 64)
			}
			items := map[string]receipt{testVideo: r}
			if run == "zero" || run == "optional_unpublished_empty" {
				items = map[string]receipt{}
				if err := os.Remove(filename); err != nil {
					t.Fatal(err)
				}
			}
			j := journal{Items: items}
			if run == "uncertain_withdrawal" {
				j.Watch = map[string][]string{testVideo: {testRoot}}
			}
			raw, _ := json.Marshal(j)
			if run != "journal_missing" && !strings.HasPrefix(run, "optional_unpublished") {
				if err := os.WriteFile(state, raw, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if run == "unreadable_manifest" {
				if err := os.WriteFile(filename, []byte("{broken}"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			var master, variant, segment object
			for _, o := range m.Objects {
				if o.Key == m.Master {
					master = o
				}
				if strings.HasSuffix(o.Key, "/index.m3u8") {
					variant = o
				}
				if strings.HasSuffix(o.Key, "/seg.m4s") {
					segment = o
				}
			}
			ranges := func(w http.ResponseWriter, req *http.Request, data []byte, damage bool) {
				t.Helper()
				if req.Header.Get("Range") != "bytes=0-8191" {
					t.Errorf("unexpected media range %q", req.Header.Get("Range"))
					http.Error(w, "range", 400)
					return
				}
				w.Header().Set("Content-Range", fmt.Sprintf("bytes 0-8191/%d", len(data)))
				w.WriteHeader(206)
				reply := append([]byte(nil), data[:8192]...)
				if damage {
					reply[0] ^= 1
				}
				if run == "short_range" {
					reply = reply[:100]
				}
				w.Write(reply)
			}
			origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				if strings.HasPrefix(run, "native_") && req.Method == "HEAD" && req.URL.Path == referencePath(m, master) && req.Header.Get("Authorization") == "" {
					switch run {
					case "native_denied":
						w.WriteHeader(404)
					case "native_uncertain":
						w.WriteHeader(503)
					default:
						w.Header().Set("Content-Length", strconv.FormatInt(master.Size, 10))
						w.WriteHeader(200)
					}
					return
				}
				if req.Method != "GET" || req.URL.Path != referencePath(m, segment) || req.Header.Get("Authorization") != "" {
					t.Error("unexpected origin request")
					w.WriteHeader(400)
					return
				}
				if run == "native_denied" {
					w.WriteHeader(404)
					return
				}
				if run == "native_uncertain" {
					w.WriteHeader(503)
					return
				}
				ranges(w, req, bodies[segment.ID], false)
			}))
			defer origin.Close()
			gateway := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				if req.Method != "GET" || req.Header.Get("Authorization") != "" {
					t.Error("unexpected gateway credentials or method")
				}
				switch req.URL.Path {
				case "/ipfs/" + testRoot + "/master.m3u8":
					data := bodies[master.ID]
					if run == "corrupt_playlist" {
						data = bytes.Repeat([]byte("x"), len(data))
					}
					w.Write(data)
				case "/ipfs/" + testRoot + "/v/index.m3u8":
					w.Write(bodies[variant.ID])
				case "/ipfs/" + testRoot + "/v/seg.m4s":
					ranges(w, req, bodies[segment.ID], run == "corrupt_gateway_media")
					if run == "revoked_during_read" {
						os.Remove(filename)
					}
				default:
					t.Error("unapproved gateway path")
					w.WriteHeader(404)
				}
			}))
			defer gateway.Close()
			calls := 0
			rpc := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				calls++
				if req.Method != "POST" || req.URL.Path != "/api/v0/pin/ls" || req.Header.Get("Authorization") != "Bearer private" || req.URL.Query().Get("stream") != "false" {
					t.Error("Kubo received a non-status request")
					w.WriteHeader(403)
					return
				}
				if run == "rpc_down" {
					w.WriteHeader(502)
					return
				}
				kind := req.URL.Query().Get("type")
				if run == "incomplete_rpc" {
					fmt.Fprint(w, `{"Keys":null}`)
					return
				}
				keys := map[string]map[string]string{}
				if kind == "recursive" && run != "pin_missing" && run != "zero" && run != "optional_unpublished_empty" {
					keys[testRoot] = map[string]string{"Type": "recursive"}
				}
				if (kind == "direct" && run == "stray_direct") || (kind == "recursive" && run == "stray") {
					keys["unrelated"] = map[string]string{"Type": kind}
				}
				if len(keys) == 0 {
					fmt.Fprint(w, "{}")
					return
				}
				json.NewEncoder(w).Encode(map[string]any{"Keys": keys})
			}))
			defer rpc.Close()
			port := func(s *httptest.Server) int {
				v, err := strconv.Atoi(strings.TrimPrefix(s.URL, "http://127.0.0.1:"))
				if err != nil {
					t.Fatal(err)
				}
				return v
			}
			dir := filepath.Dir(filename)
			if run == "approval_directory_missing" {
				dir = filepath.Join(dir, "absent")
			}
			cfg := statusConfig{RPCPort: port(rpc), GatewayPort: port(gateway), Sources: []statusSource{{Approvals: dir, Journal: state, OriginPort: port(origin), AllowUnpublished: strings.HasPrefix(run, "optional_unpublished")}}}
			status := (publisher{client: rpc.Client(), rpc: rpc.URL, token: "private"}).collectStatus(context.Background(), cfg)
			if status.Reason != want {
				t.Fatalf("%+v, want %s", status, want)
			}
			if want == "verified" {
				n := 1
				if run == "zero" || run == "optional_unpublished_empty" {
					n = 0
				}
				if status.State != "ok" || status.Pinned == nil || *status.Pinned != n || calls != 4 {
					t.Fatalf("unverified inventory %+v, calls=%d", status, calls)
				}
			} else if status.Pinned != nil {
				t.Fatal("published count for incomplete observation")
			}
			if _, err := time.Parse(time.RFC3339Nano, status.ObservedAt); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestStatusFileIsAtomicAndContainsOnlyTheWireContract(t *testing.T) {
	target := filepath.Join(t.TempDir(), "status.json")
	n := 0
	if err := writeStatus(target, statusValue("verified", &n)); err != nil {
		t.Fatal(err)
	}
	old, err := os.Open(target)
	if err != nil {
		t.Fatal(err)
	}
	defer old.Close()
	if err := runStatus([]string{"--config", filepath.Join(t.TempDir(), "absent"), "--output", target}); err != nil {
		t.Fatal(err)
	}
	var first, second map[string]any
	if err = json.NewDecoder(old).Decode(&first); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(raw, &second); err != nil {
		t.Fatal(err)
	}
	if first["pinned"] != float64(0) || len(first) != 5 || len(second) != 4 || second["state"] != "down" || second["reason"] != "approval_unavailable" || second["version"] != float64(1) || len(raw) > 4096 {
		t.Fatalf("unexpected snapshots: %v %v", first, second)
	}
	st, err := os.Stat(target)
	if err != nil || st.Mode().Perm() != 0644 {
		t.Fatal("snapshot unreadable by consumer")
	}
}
