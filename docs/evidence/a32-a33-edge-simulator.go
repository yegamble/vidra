// Command a32-a33-edge-simulator is a disposable CDN edge for acceptance
// testing. It is a caching reverse proxy in front of a media origin, plus the
// single-URL invalidation endpoint internal/cdn actually speaks — so a lab can
// prove the shipped purge contract end to end without a commercial CDN account.
//
// # The origin is the API, and the cache key is the whole request URI
//
// The first revision of this fixture sat in front of an object-store bucket and
// keyed its cache on the request PATH, because that is what a key-addressed
// edge URL is: `base + "/" + <object key>`, with no query anywhere. vidra-core
// #199 reversed that model — the CDN's origin is now the Vidra API itself and
// an edge URL is `base + <this API's own media route path and query> +
// &__vidra_edge=1` — so a path-keyed cache would be wrong in two ways that both
// silently pass: it would collapse every generation of a segment onto one entry
// (the `?v=` tag is in the query, and versioning the edge is the whole point of
// putting it there), and it would drop the `__vidra_edge=1` marker on the
// origin fetch, so the API would answer the edge with a redirect back to the
// edge instead of the bytes. The cache key and the origin fetch therefore both
// carry the full request URI — path AND query — which is also exactly what
// internal/cdn purges: cdn.Provider.Purge rebuilds the same URL EdgeURL handed
// the viewer, marker and all.
//
// It exists because INT-10's procedure says "edge simulator first, then
// selected edge", and because the two claims that row makes — "stale segments
// must never play" and "failed purge is visible" — can only be tested against
// something that HOLDS a copy after the origin's bytes have changed. A plain
// reverse proxy would pass every test by never caching anything.
//
// It is NOT a CDN. It has one node, an unbounded in-memory cache, no TTL
// eviction (entries live until purged or the process exits), no compression, no
// TLS and no persistence. That is deliberate: every one of those would make a
// stale hit harder to observe, and observing stale hits is the whole point.
//
// # The purge contract it implements
//
// internal/cdn sends exactly one request per object key:
//
//	<DELIVERY_CDN_PURGE_METHOD> <DELIVERY_CDN_PURGE_URL with {url}/{url_encoded}/{key} substituted>
//	<DELIVERY_CDN_PURGE_HEADER>: <DELIVERY_CDN_PURGE_TOKEN>
//
// and reads only the status code: 2xx and 404 are success, everything else is
// an error. This simulator answers 200 when it held the object, 404 when it did
// not (the nginx cache-purge module's behaviour, which is why internal/cdn
// treats 404 as success), 403 when the token is missing or wrong, and whatever
// -fail-purge says when failure is being injected.
//
// # Usage
//
//	go run a32-a33-edge-simulator.go \
//	  -listen 127.0.0.1:9310 \
//	  -origin http://127.0.0.1:8088 \
//	  -purge-method PURGE \
//	  -purge-header X-Edge-Purge-Token \
//	  -purge-token <a throwaway value, never a real credential> \
//	  -allow-origin http://127.0.0.1:8099
//
// with the API configured as:
//
//	DELIVERY_CDN_BASE_URL=http://127.0.0.1:9310
//	DELIVERY_CDN_PURGE_URL={url}
//	DELIVERY_CDN_PURGE_METHOD=PURGE
//	DELIVERY_CDN_PURGE_HEADER=X-Edge-Purge-Token
//	DELIVERY_CDN_PURGE_TOKEN=<the same throwaway value>
//
// # Control surface
//
// Under /__edge/, which no storage key can collide with (every Vidra key starts
// with a known media prefix, and the proxy refuses a request path beginning
// "__edge" as an object):
//
//	GET  /__edge/state              cache entries, hit/miss counters, purge log
//	POST /__edge/fail?purge=500     purge answers 500 until reset (also: timeout, 403)
//	POST /__edge/fail?serve=502     GETs answer 502 until reset ("failure after redirect")
//	POST /__edge/fail?reset=1       clear both injections
//	POST /__edge/reset              clear the cache and the counters
//
// Nothing here is credential-free by accident: the token is a command-line flag
// so no secret is ever written into this file, and the file is committed only
// because it contains none.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// entry is one cached object: the origin's status, the headers worth
// reproducing, and the whole body. Bodies are held entire so a Range request
// against a HIT can be answered from the cache rather than by re-contacting the
// origin — an edge that re-fetched on Range could never be caught serving
// stale bytes.
type entry struct {
	status   int
	header   http.Header
	body     []byte
	storedAt time.Time
}

type edge struct {
	origin      *url.URL
	allowOrigin string
	purgeMethod string
	purgeHeader string
	purgeToken  string

	mu        sync.Mutex
	cache     map[string]*entry
	hits      int
	misses    int
	purges    []purgeRecord
	failPurge string // "", "500", "403", "timeout"
	failServe string // "", "502", ...
}

type purgeRecord struct {
	At     string `json:"at"`
	Key    string `json:"key"`
	Status int    `json:"status"`
	Held   bool   `json:"held"`
	Auth   bool   `json:"authorized"`
}

func main() {
	listen := flag.String("listen", "127.0.0.1:9310", "listen address")
	origin := flag.String("origin", "", "media origin base — the Vidra API, e.g. http://127.0.0.1:8088")
	allowOrigin := flag.String("allow-origin", "", "value for Access-Control-Allow-Origin on proxied responses")
	purgeMethod := flag.String("purge-method", "PURGE", "method the purge endpoint accepts")
	purgeHeader := flag.String("purge-header", "X-Edge-Purge-Token", "header carrying the purge token")
	purgeToken := flag.String("purge-token", "", "expected purge token value (throwaway; never a real credential)")
	flag.Parse()

	if *origin == "" {
		log.Fatal("edge: -origin is required")
	}
	base, err := url.Parse(strings.TrimRight(*origin, "/"))
	if err != nil || base.Host == "" {
		log.Fatalf("edge: -origin %q must be an absolute http(s) URL", *origin)
	}
	e := &edge{
		origin:      base,
		allowOrigin: *allowOrigin,
		purgeMethod: strings.ToUpper(*purgeMethod),
		purgeHeader: *purgeHeader,
		purgeToken:  *purgeToken,
		cache:       map[string]*entry{},
	}
	log.Printf("edge: listening on %s, origin %s, purge %s %s", *listen, base, e.purgeMethod, e.purgeHeader)
	log.Fatal(http.ListenAndServe(*listen, e))
}

func (e *edge) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.EscapedPath(), "/")
	if strings.HasPrefix(path, "__edge/") || path == "__edge" {
		e.control(w, r)
		return
	}
	// The cache key is the whole request URI, query included. See the package
	// comment: with the API as origin the ?v= generation tag and the
	// __vidra_edge=1 marker both live in the query, and both are load-bearing.
	key := path
	if r.URL.RawQuery != "" {
		key += "?" + r.URL.RawQuery
	}
	switch {
	case r.Method == e.purgeMethod:
		e.purge(w, r, key)
	case r.Method == http.MethodOptions:
		e.preflight(w, r)
	case r.Method == http.MethodGet, r.Method == http.MethodHead:
		e.serve(w, r, key)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

// purge implements the invalidation half of the contract. See the package
// comment for why 404 is a success answer and not an error.
func (e *edge) purge(w http.ResponseWriter, r *http.Request, key string) {
	e.mu.Lock()
	inject := e.failPurge
	e.mu.Unlock()

	authorized := e.purgeToken == "" || r.Header.Get(e.purgeHeader) == e.purgeToken
	record := func(status int, held bool) {
		e.mu.Lock()
		e.purges = append(e.purges, purgeRecord{
			At: time.Now().UTC().Format(time.RFC3339Nano), Key: key, Status: status, Held: held, Auth: authorized,
		})
		e.mu.Unlock()
	}
	if !authorized {
		record(http.StatusForbidden, false)
		http.Error(w, "bad purge token", http.StatusForbidden)
		return
	}
	switch inject {
	case "timeout":
		// Sleep past any plausible DELIVERY_CDN_PURGE_TIMEOUT and then answer,
		// so the caller's own timeout is what fires.
		record(0, false)
		time.Sleep(90 * time.Second)
		return
	case "":
	default:
		code, err := strconv.Atoi(inject)
		if err != nil {
			code = http.StatusInternalServerError
		}
		record(code, false)
		http.Error(w, "injected purge failure", code)
		return
	}
	e.mu.Lock()
	_, held := e.cache[key]
	delete(e.cache, key)
	e.mu.Unlock()
	status := http.StatusNotFound
	if held {
		status = http.StatusOK
	}
	record(status, held)
	w.WriteHeader(status)
	_, _ = io.WriteString(w, "purged="+strconv.FormatBool(held)+"\n")
}

// serve answers a viewer request from the cache, filling it from the origin on
// a miss. A HIT never contacts the origin — that is what makes a stale copy
// observable after the origin's bytes have changed.
func (e *edge) serve(w http.ResponseWriter, r *http.Request, key string) {
	e.mu.Lock()
	inject := e.failServe
	cached := e.cache[key]
	e.mu.Unlock()

	if inject != "" {
		code, err := strconv.Atoi(inject)
		if err != nil {
			code = http.StatusBadGateway
		}
		e.cors(w)
		http.Error(w, "injected edge failure", code)
		return
	}
	state := "HIT"
	if cached == nil {
		fetched, err := e.fetch(key)
		if err != nil {
			e.cors(w)
			http.Error(w, "edge: origin fetch failed", http.StatusBadGateway)
			return
		}
		state = "MISS"
		cached = fetched
		// Only a complete 200 is cacheable; anything else is passed through
		// once so an origin error can never become a permanent edge answer.
		if fetched.status == http.StatusOK {
			e.mu.Lock()
			e.cache[key] = fetched
			e.misses++
			e.mu.Unlock()
		} else {
			e.mu.Lock()
			e.misses++
			e.mu.Unlock()
		}
	} else {
		e.mu.Lock()
		e.hits++
		e.mu.Unlock()
	}

	h := w.Header()
	for _, name := range []string{"Content-Type", "ETag", "Last-Modified", "Cache-Control", "Content-Disposition"} {
		if v := cached.header.Get(name); v != "" {
			h.Set(name, v)
		}
	}
	h.Set("X-Edge-Cache", state)
	h.Set("X-Edge-Stored-At", cached.storedAt.UTC().Format(time.RFC3339))
	h.Set("Accept-Ranges", "bytes")
	e.cors(w)

	if cached.status != http.StatusOK {
		w.WriteHeader(cached.status)
		if r.Method != http.MethodHead {
			_, _ = w.Write(cached.body)
		}
		return
	}
	start, end, ok := parseRange(r.Header.Get("Range"), len(cached.body))
	if !ok {
		h.Set("Content-Length", strconv.Itoa(len(cached.body)))
		w.WriteHeader(http.StatusOK)
		if r.Method != http.MethodHead {
			_, _ = w.Write(cached.body)
		}
		return
	}
	h.Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, len(cached.body)))
	h.Set("Content-Length", strconv.Itoa(end-start+1))
	w.WriteHeader(http.StatusPartialContent)
	if r.Method != http.MethodHead {
		_, _ = w.Write(cached.body[start : end+1])
	}
}

// fetch pulls one object from the origin, whole, at the same request URI the
// edge was asked for — including the query, which carries the ?v= generation
// tag and the __vidra_edge=1 marker the API reads to recognise its own edge.
// Range is never forwarded: the cache holds complete bodies so it can answer
// any later Range itself.
func (e *edge) fetch(key string) (*entry, error) {
	target := e.origin.String() + "/" + key
	resp, err := http.Get(target) //nolint:gosec // lab fixture, operator-supplied origin
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 512<<20))
	if err != nil {
		return nil, err
	}
	return &entry{status: resp.StatusCode, header: resp.Header.Clone(), body: body, storedAt: time.Now()}, nil
}

// preflight answers the browser's OPTIONS for a cross-origin ranged fetch.
func (e *edge) preflight(w http.ResponseWriter, r *http.Request) {
	e.cors(w)
	h := w.Header()
	h.Set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
	if req := r.Header.Get("Access-Control-Request-Headers"); req != "" {
		h.Set("Access-Control-Allow-Headers", req)
	} else {
		h.Set("Access-Control-Allow-Headers", "Range")
	}
	h.Set("Access-Control-Max-Age", "600")
	w.WriteHeader(http.StatusNoContent)
}

func (e *edge) cors(w http.ResponseWriter) {
	if e.allowOrigin == "" {
		return
	}
	h := w.Header()
	h.Set("Access-Control-Allow-Origin", e.allowOrigin)
	h.Set("Vary", "Origin")
	h.Set("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges, X-Edge-Cache, X-Edge-Stored-At")
}

func (e *edge) control(w http.ResponseWriter, r *http.Request) {
	switch strings.TrimPrefix(r.URL.Path, "/__edge/") {
	case "state":
		e.mu.Lock()
		keys := make([]string, 0, len(e.cache))
		sizes := map[string]int{}
		for k, v := range e.cache {
			keys = append(keys, k)
			sizes[k] = len(v.body)
		}
		out := map[string]any{
			"entries": keys, "sizes": sizes, "hits": e.hits, "misses": e.misses,
			"purges": e.purges, "fail_purge": e.failPurge, "fail_serve": e.failServe,
		}
		e.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(out)
	case "fail":
		q := r.URL.Query()
		e.mu.Lock()
		if q.Get("reset") != "" {
			e.failPurge, e.failServe = "", ""
		}
		if v := q.Get("purge"); v != "" {
			e.failPurge = v
		}
		if v := q.Get("serve"); v != "" {
			e.failServe = v
		}
		state := map[string]string{"fail_purge": e.failPurge, "fail_serve": e.failServe}
		e.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(state)
	case "reset":
		e.mu.Lock()
		e.cache = map[string]*entry{}
		e.hits, e.misses, e.purges = 0, 0, nil
		e.mu.Unlock()
		w.WriteHeader(http.StatusNoContent)
	default:
		http.NotFound(w, r)
	}
}

// parseRange understands the one form a media player sends: a single
// "bytes=start-[end]". Anything else is served whole, which is a legal answer
// to a Range request and keeps the fixture small.
func parseRange(header string, size int) (int, int, bool) {
	if !strings.HasPrefix(header, "bytes=") || size == 0 {
		return 0, 0, false
	}
	spec := strings.TrimPrefix(header, "bytes=")
	if strings.Contains(spec, ",") {
		return 0, 0, false
	}
	parts := strings.SplitN(spec, "-", 2)
	if len(parts) != 2 || parts[0] == "" {
		return 0, 0, false
	}
	start, err := strconv.Atoi(parts[0])
	if err != nil || start < 0 || start >= size {
		return 0, 0, false
	}
	end := size - 1
	if parts[1] != "" {
		if end, err = strconv.Atoi(parts[1]); err != nil {
			return 0, 0, false
		}
	}
	if end >= size {
		end = size - 1
	}
	if end < start {
		return 0, 0, false
	}
	return start, end, true
}
