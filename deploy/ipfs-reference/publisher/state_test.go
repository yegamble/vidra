package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type mockPins struct {
	pinned, unknown, failAfterAdd, withdrawDuringAdd bool
	adds, removes                                    int
	filename                                         string
}

func (n *mockPins) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch r.URL.Path {
	case "/api/v0/pin/ls":
		if n.unknown {
			http.NotFound(w, r)
		} else if n.pinned {
			fmt.Fprintf(w, `{"Keys":{%q:{"Type":"recursive"}}}`, testRoot)
		} else {
			fmt.Fprint(w, `{"Keys":{}}`)
		}
	case "/api/v0/pin/add":
		n.adds++
		n.pinned = true
		if n.withdrawDuringAdd {
			os.Remove(n.filename)
		}
		if n.failAfterAdd {
			n.unknown = true
			fmt.Fprint(w, "{")
			return
		}
		fmt.Fprintf(w, `{"Pins":[%q]}`, testRoot)
	case "/api/v0/pin/rm":
		n.removes++
		n.pinned = false
		fmt.Fprintf(w, `{"Pins":[%q]}`, testRoot)
	default:
		http.NotFound(w, r)
	}
}

func stateFixture(t *testing.T) (publisher, *mockPins, string, manifest) {
	t.Helper()
	filename, m, bodies := sample(t)
	_, files, err := readApproval(filename)
	if err != nil {
		t.Fatal(err)
	}
	master := bodies[files["master.m3u8"].ID]
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Range", fmt.Sprintf("bytes 0-%d/%d", len(master)-1, len(master)))
		w.Header().Set("Content-Length", fmt.Sprint(len(master)))
		w.WriteHeader(http.StatusPartialContent)
		w.Write(master)
	}))
	t.Cleanup(source.Close)
	n := &mockPins{filename: filename}
	rpc := httptest.NewServer(n)
	t.Cleanup(rpc.Close)
	return publisher{client: rpc.Client(), rpc: rpc.URL, origin: source.URL, token: "test", stateDir: filepath.Join(t.TempDir(), "state")}, n, filename, m
}

func TestPublicationRecoversUncertainPin(t *testing.T) {
	p, n, filename, m := stateFixture(t)
	ctx := context.Background()
	n.failAfterAdd = true
	if err := p.commitPin(ctx, filename, m, testRoot); err == nil {
		t.Fatal("lost pin response and unavailable status were reported as success")
	}
	if err := p.withJournal(ctx, func(j *journal) error {
		r := j.Items[m.Video]
		if r.State != "pending" || r.Root != testRoot || !r.Owned {
			t.Errorf("missing pending receipt: %+v", r)
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(filepath.Join(p.stateDir, "publications.json"))
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("state permissions: %v, %v", info, err)
	}
	n.unknown = false
	for i := 0; i < 2; i++ {
		root, err := p.publish(ctx, filename)
		if err != nil || root != testRoot || n.adds != 1 {
			t.Fatalf("retry %d: %s, %v, adds=%d", i, root, err, n.adds)
		}
	}
	if err := os.Remove(filename); err != nil {
		t.Fatal(err)
	}
	n.unknown = true
	if _, err := p.reconcile(ctx, filename); err == nil {
		t.Fatal("unknown pin status was treated as absent")
	}
	n.unknown = false
	if root, err := p.reconcile(ctx, filename); err != nil || root != "" || n.pinned || n.removes != 1 {
		t.Fatalf("withdrawal: %s, %v, node=%+v", root, err, n)
	}
}

func TestApprovalRemovedWhilePinning(t *testing.T) {
	p, n, filename, m := stateFixture(t)
	n.withdrawDuringAdd = true
	if err := p.commitPin(context.Background(), filename, m, testRoot); !errors.Is(err, errApprovalLost) || n.pinned || n.removes != 1 {
		t.Fatalf("err=%v, node=%+v", err, n)
	}
}

func TestPublicationPreservesSharedAndPreexistingRoots(t *testing.T) {
	for _, preexisting := range []bool{false, true} {
		t.Run(fmt.Sprint(preexisting), func(t *testing.T) {
			p, n, first, m := stateFixture(t)
			ctx := context.Background()
			n.pinned = preexisting
			if err := p.commitPin(ctx, first, m, testRoot); err != nil {
				t.Fatal(err)
			}
			old := m.Video
			m.Video = "befacf00-d86f-4a64-855b-8545357a7a50"
			m.Master = strings.ReplaceAll(m.Master, old, m.Video)
			for i := range m.Objects {
				m.Objects[i].Key = strings.ReplaceAll(m.Objects[i].Key, old, m.Video)
				m.Objects[i].ID = objectID(m, m.Objects[i])
			}
			second := filepath.Join(filepath.Dir(first), m.Video+".json")
			raw, _ := json.Marshal(m)
			if err := os.WriteFile(second, raw, 0600); err != nil {
				t.Fatal(err)
			}
			if err := p.commitPin(ctx, second, m, testRoot); err != nil {
				t.Fatal(err)
			}
			if err := os.Remove(first); err != nil {
				t.Fatal(err)
			}
			if _, err := p.reconcile(ctx, first); err != nil || !n.pinned || n.removes != 0 {
				t.Fatalf("shared root removed: %v, %+v", err, n)
			}
			if err := os.Remove(second); err != nil {
				t.Fatal(err)
			}
			if _, err := p.reconcile(ctx, second); err != nil || n.pinned != preexisting {
				t.Fatalf("last withdrawal: %v, %+v", err, n)
			}
		})
	}
}

func TestWithdrawnPendingPinCanCompleteLate(t *testing.T) {
	p, n, filename, m := stateFixture(t)
	ctx := context.Background()
	n.failAfterAdd = true
	if err := p.commitPin(ctx, filename, m, testRoot); err == nil {
		t.Fatal("lost confirmation")
	}
	if err := os.Remove(filename); err != nil {
		t.Fatal(err)
	}
	n.unknown = false
	n.pinned = false // node resumed before the old pin request finished
	if _, err := p.reconcile(ctx, filename); err != nil {
		t.Fatal(err)
	}
	n.pinned = true // late completion after the first withdrawal check
	if _, err := p.reconcile(ctx, filename); err != nil || n.pinned || n.removes != 1 {
		t.Fatalf("late pin survived: err=%v node=%+v", err, n)
	}
}
