package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestWatchBridgeOnlyServesCurrentApprovedPinnedMembers(t *testing.T) {
	filename, m, original := sample(t)
	syntheticMaster := m.Master
	directory := "streaming-playlists/" + m.Video + "/r7/"
	m.Master = directory + "master.m3u8"
	bodies := map[string][]byte{}
	for i := range m.Objects {
		entry := &m.Objects[i]
		name := strings.TrimPrefix(entry.Key, path.Dir(syntheticMaster)+"/")
		bodies[name] = original[entry.ID]
		entry.Key = directory + name
		entry.ID = objectID(m, *entry)
	}
	writeJSON := func(filename string, value any) {
		t.Helper()
		data, err := json.Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filename, data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	writeJSON(filename, m)
	state := filepath.Join(t.TempDir(), "publications.json")
	record := receipt{Root: testRoot, Approval: approvalHash(m), State: "pinned"}
	j := journal{Items: map[string]receipt{m.Video: record}}
	writeJSON(state, j)
	pinned := true
	rpc := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v0/pin/ls" || r.Header.Get("Authorization") != "Bearer reader" {
			t.Error("unexpected RPC request")
			w.WriteHeader(403)
			return
		}
		if pinned {
			json.NewEncoder(w).Encode(map[string]any{"Keys": map[string]any{testRoot: map[string]string{"Type": "recursive"}}})
		} else {
			w.Write([]byte("{}"))
		}
	}))
	defer rpc.Close()
	var revokeDuringRead bool
	gateway := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		name, ok := strings.CutPrefix(r.URL.Path, "/ipfs/"+testRoot+"/")
		body, exists := bodies[name]
		if !ok || !exists || r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" {
			t.Error("unexpected gateway request")
			w.WriteHeader(404)
			return
		}
		if revokeDuringRead {
			if err := os.Remove(filename); err != nil {
				t.Error(err)
			}
		}
		http.ServeContent(w, r, name, time.Time{}, bytes.NewReader(body))
	}))
	defer gateway.Close()
	u, _ := url.Parse(gateway.URL)
	port, _ := strconv.Atoi(u.Port())
	config := statusConfig{GatewayPort: port, Sources: []statusSource{{Approvals: filepath.Dir(filename), Journal: state}}}
	b := watchBridge{config: config, node: publisher{rpc: rpc.URL, token: "reader", client: gateway.Client()}}
	base := "/api/v1/videos/" + m.Video + "/ipfs-reference/"
	check := func(method, name, span string, want int, wantBody []byte) {
		t.Helper()
		req := httptest.NewRequest(method, base+name, nil)
		req.Header.Set("Authorization", "Bearer viewer")
		req.Header.Set("Cookie", "viewer=private")
		if span != "" {
			req.Header.Set("Range", span)
		}
		w := httptest.NewRecorder()
		b.ServeHTTP(w, req)
		if w.Code != want || !bytes.Equal(w.Body.Bytes(), wantBody) || w.Header().Get("Cache-Control") != "private, no-store" {
			t.Fatalf("%s %s: status %d, %d bytes", method, name, w.Code, w.Body.Len())
		}
	}
	check("HEAD", "r7/master.m3u8", "", 200, nil)
	check("GET", "r7/v/index.m3u8", "", 200, bodies["v/index.m3u8"])
	check("GET", "r7/v/seg.m4s", "bytes=1-9", 206, bodies["v/seg.m4s"][1:10])
	check("GET", "r7/v/init.mp4", "bytes=-2", 206, bodies["v/init.mp4"][2:])
	check("GET", "r7/v/init.mp4", "bytes=77-", 416, nil)
	check("GET", "r6/master.m3u8", "", 404, nil)
	check("GET", "r7/v/unknown.mp4", "", 404, nil)
	check("GET", "r7/master.m3u8?anything=1", "", 404, nil)
	check("GET", "r7/%2e%2e/master.m3u8", "", 404, nil)
	check("POST", "r7/master.m3u8", "", 405, nil)
	pinned = false
	check("GET", "r7/master.m3u8", "", 404, nil)
	pinned = true
	record.State = "withdrawing"
	j.Items[m.Video] = record
	writeJSON(state, j)
	check("GET", "r7/master.m3u8", "", 404, nil)
	record.State = "pinned"
	j.Items[m.Video] = record
	writeJSON(state, j)
	revokeDuringRead = true
	check("GET", "r7/v/init.mp4", "", 404, nil)
	check("GET", "r7/master.m3u8", "", 404, nil)
}
