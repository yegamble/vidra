// Command a29-ap-peer is a minimal ActivityPub peer for acceptance testing. It
// serves WebFinger and one Person actor whose RSA keypair the lab holds, and it
// can POST an arbitrary activity to a remote inbox four ways: correctly signed
// (cavage draft, rsa-sha256, covering (request-target) host date digest),
// unsigned, signed-then-corrupted (one byte of the signature flipped while
// keyId, Date, Digest and the covered set stay valid), or signed under someone
// else's keyId.
//
// It exists because INT-05's procedure says "signed inbox/outbox", and the only
// way to prove an inbox REFUSES is to send it something a real Vidra instance
// cannot produce. Two vidra instances talking to each other exercise the happy
// path and nothing else: every activity they emit is correctly signed by
// construction, so a lab built only from them would pass with signature
// verification deleted.
//
// Usage, as A29 ran it:
//
//	go run a29-ap-peer.go -serve -port 38080 -origin http://127.0.0.1:38080 \
//	    -key /tmp/peer.pem -name hostile
//	go run a29-ap-peer.go -post http://127.0.0.1:18080/inbox -body follow.json \
//	    -mode tampered -key /tmp/peer.pem
//
// The keypair is generated on first use and written to -key. It is a THROWAWAY
// lab identity: never point this at an instance you do not own, and never
// commit a generated key.
package main

import (
	"bytes"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

var (
	origin  = flag.String("origin", "http://127.0.0.1:38080", "this peer's public origin")
	keyPath = flag.String("key", "peer.pem", "PKCS#8 private key PEM path (created if absent)")
	name    = flag.String("name", "hostile", "preferredUsername of the served Person actor")
	serve   = flag.Bool("serve", false, "run the actor/webfinger server")
	port    = flag.String("port", "38080", "listen port when serving")

	post    = flag.String("post", "", "inbox URL to POST an activity to")
	bodyF   = flag.String("body", "", "activity JSON file to POST")
	mode    = flag.String("mode", "signed", "signed | unsigned | tampered | badkeyid")
	asKeyID = flag.String("keyid", "", "override the keyId (default <origin>/accounts/<name>#main-key)")
)

func loadKey() *rsa.PrivateKey {
	if b, err := os.ReadFile(*keyPath); err == nil {
		blk, _ := pem.Decode(b)
		k, err := x509.ParsePKCS8PrivateKey(blk.Bytes)
		if err != nil {
			panic(err)
		}
		return k.(*rsa.PrivateKey)
	}
	k, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		panic(err)
	}
	der, _ := x509.MarshalPKCS8PrivateKey(k)
	_ = os.WriteFile(*keyPath, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}), 0o600)
	return k
}

func pubPEM(k *rsa.PrivateKey) string {
	der, _ := x509.MarshalPKIXPublicKey(&k.PublicKey)
	return string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der}))
}

func main() {
	flag.Parse()
	key := loadKey()
	actorURL := *origin + "/accounts/" + *name
	keyID := actorURL + "#main-key"
	if *asKeyID != "" {
		keyID = *asKeyID
	}

	if *serve {
		mux := http.NewServeMux()
		mux.HandleFunc("/.well-known/webfinger", func(w http.ResponseWriter, r *http.Request) {
			res := r.URL.Query().Get("resource")
			w.Header().Set("Content-Type", "application/jrd+json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"subject": res,
				"links": []any{map[string]any{
					"rel": "self", "type": "application/activity+json", "href": actorURL,
				}},
			})
		})
		mux.HandleFunc("/accounts/"+*name, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/activity+json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"@context":          []string{"https://www.w3.org/ns/activitystreams", "https://w3id.org/security/v1"},
				"id":                actorURL,
				"type":              "Person",
				"preferredUsername": *name,
				"inbox":             actorURL + "/inbox",
				"outbox":            actorURL + "/outbox",
				"followers":         actorURL + "/followers",
				"following":         actorURL + "/following",
				"publicKey": map[string]any{
					"id": keyID, "owner": actorURL, "publicKeyPem": pubPEM(key),
				},
			})
		})
		mux.HandleFunc("/accounts/"+*name+"/inbox", func(w http.ResponseWriter, r *http.Request) {
			b, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
			fmt.Fprintf(os.Stderr, "INBOX %s\n", string(b))
			w.WriteHeader(http.StatusAccepted)
		})
		fmt.Fprintf(os.Stderr, "a29peer serving %s on :%s\n", actorURL, *port)
		if err := http.ListenAndServe("127.0.0.1:"+*port, mux); err != nil {
			panic(err)
		}
		return
	}

	if *post == "" || *bodyF == "" {
		fmt.Fprintln(os.Stderr, "need -serve, or -post URL -body FILE")
		os.Exit(2)
	}
	body, err := os.ReadFile(*bodyF)
	if err != nil {
		panic(err)
	}
	req, err := http.NewRequest(http.MethodPost, *post, bytes.NewReader(body))
	if err != nil {
		panic(err)
	}
	req.Header.Set("Content-Type", "application/activity+json")
	if *mode != "unsigned" {
		req.Header.Set("Date", time.Now().UTC().Format(http.TimeFormat))
		sum := sha256.Sum256(body)
		req.Header.Set("Digest", "SHA-256="+base64.StdEncoding.EncodeToString(sum[:]))
		covered := []string{"(request-target)", "host", "date", "digest"}
		var lines []string
		for _, h := range covered {
			switch h {
			case "(request-target)":
				lines = append(lines, "(request-target): post "+req.URL.RequestURI())
			case "host":
				lines = append(lines, "host: "+req.URL.Host)
			default:
				lines = append(lines, h+": "+req.Header.Get(h))
			}
		}
		hashed := sha256.Sum256([]byte(strings.Join(lines, "\n")))
		sig, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, hashed[:])
		if err != nil {
			panic(err)
		}
		enc := base64.StdEncoding.EncodeToString(sig)
		if *mode == "tampered" {
			// Flip one byte of the signature: everything else about the request
			// — keyId, Date, Digest, covered set — stays valid.
			raw, _ := base64.StdEncoding.DecodeString(enc)
			raw[10] ^= 0xff
			enc = base64.StdEncoding.EncodeToString(raw)
		}
		req.Header.Set("Signature", fmt.Sprintf(`keyId=%q,algorithm="rsa-sha256",headers=%q,signature=%q`,
			keyID, strings.Join(covered, " "), enc))
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		panic(err)
	}
	defer func() { _ = resp.Body.Close() }()
	rb, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	fmt.Printf("%d %s\n", resp.StatusCode, strings.TrimSpace(string(rb)))
}
