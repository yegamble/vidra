#!/usr/bin/env bash
# edge-ap-probe.sh - does the edge in front of YOUR instance let ActivityPub through?
#
# Run it by hand against your own instance (never someone else's). It sends GET
# requests plus ONE unsigned `{}` POST to /inbox, and prints PASS/FAIL/WARN per
# check with the observed status and headers. Exit 1 on any FAIL, 2 on bad usage.
#
# WHY it exists: a CDN/WAF/reverse proxy can break federation without the app
# ever seeing a request - it serves an HTML bot challenge to a peer that cannot
# solve it, or it caches the ActivityPub representation of /accounts/x and then
# serves JSON to browsers (or HTML to peers) because the cache key ignores
# Accept. None of that shows up in the app's logs or in any compose-level test.
# The probe separates "the app answered" (including "federation is off") from
# "the edge answered instead of the app".
#
#   bash tests/edge-ap-probe.sh --base-url https://example.test \
#        [--account NAME] [--video UUID] [--pre-503]
#
# Without --account the actor checks are skipped (WARN): an actor id is needed.
# --video probes /videos/UUID (the id vidra federates) and the legacy
#   /videos/watch/UUID.
# --pre-503: the instance runs vidra-core v0.7.25 or older, which answers 404
#   (not 503 federation_disabled) to ActivityPub while federation is off. Without
#   it a 404 on an actor, video or inbox is a FAIL, because a 404 can equally be
#   an unknown account or an edge rule; with it that 404 is only a WARN.
# CURL=/path/to/curl overrides the binary (the unit test stubs it).
#USAGE_END
set -euo pipefail

CURL=${CURL:-curl}
# A federation peer's User-Agent, not a browser's: bot rules key on this.
UA='PeerTube/8.3.2 (+https://peer.example.test)'

log() { printf '%s\n' "$*"; }
die() { printf 'edge-ap-probe: %s\n' "$*" >&2; exit 2; }

BASE='' ACCOUNT='' VIDEO='' PRE503=0
while [ $# -gt 0 ]; do
  case $1 in
    --base-url) [ $# -ge 2 ] || die '--base-url needs a value'; BASE=$2; shift 2 ;;
    --account)  [ $# -ge 2 ] || die '--account needs a value';  ACCOUNT=$2; shift 2 ;;
    --video)    [ $# -ge 2 ] || die '--video needs a value';    VIDEO=$2; shift 2 ;;
    --pre-503)  PRE503=1; shift ;;
    -h|--help)  sed -n '2,/^#USAGE_END/p' "$0" | sed '$d'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ -n "$BASE" ] || die '--base-url is required (e.g. --base-url https://example.test)'
case $BASE in http://*|https://*) ;; *) die '--base-url must start with http:// or https://' ;; esac
BASE=${BASE%/}
HOST=${BASE#*://}
HOST=${HOST%%/*}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

FAILS=0 WARNS=0 FED_OFF=0
pass() { log "PASS  $1"; }
warn() { log "WARN  $1"; WARNS=$((WARNS + 1)); }
fail() { log "FAIL  $1"; FAILS=$((FAILS + 1)); }

# fetch METHOD PATH ACCEPT [CONTENT-TYPE BODY]
# Sets F_STATUS F_CTYPE F_VARY F_HDRS (header file) F_BODY (body file) F_SEEN
# (one-line summary for the report). On a GET the headers kept are the FINAL
# response's.
fetch() {
  local method=$1 path=$2 accept=$3 ctype=${4:-} body=${5:-}
  local args=(-sS -m 20 -A "$UA" -H "Accept: $accept" -D "$TMP/h.raw" -o "$TMP/body" -w '%{http_code}')
  # A GET follows redirects (a peer does). The POST does not: -L would turn a 3xx
  # on the inbox into a GET and hide that the edge redirects it.
  if [ "$method" = GET ]; then args+=(-L --max-redirs 3)
  else args+=(-X "$method" -H "Content-Type: $ctype" --data "$body"); fi
  : >"$TMP/h.raw"; : >"$TMP/body"
  F_STATUS=$("$CURL" "${args[@]}" "$BASE$path" 2>"$TMP/err") || F_STATUS=000
  # -L leaves one header block per hop; keep the last one.
  tr -d '\r' <"$TMP/h.raw" | awk '/^HTTP\//{h=""} {h=h $0 "\n"} END{printf "%s", h}' >"$TMP/hdrs"
  F_HDRS=$TMP/hdrs F_BODY=$TMP/body
  F_CTYPE=$(hdr content-type) F_VARY=$(all_hdr vary)
  F_SEEN="status=$F_STATUS content-type=${F_CTYPE:--} vary=${F_VARY:--}"
  if [ "$F_STATUS" = 000 ]; then F_SEEN="no response ($(head -c 200 "$TMP/err" | tr '\n' ' '))"; fi
}

# hdr NAME: last value of a response header, empty if absent.
hdr() { grep -i "^$1:" "$F_HDRS" | tail -1 | sed 's/^[^:]*:[[:space:]]*//' || true; }
# all_hdr NAME: every value of a header joined with ", " (a header may repeat).
all_hdr() { grep -i "^$1:" "$F_HDRS" | sed 's/^[^:]*:[[:space:]]*//' | paste -sd, - | sed 's/,/, /g' || true; }
# vary_has_accept: a Vary TOKEN equal to accept or *. A substring match would
# take Accept-Encoding for Accept, a header every CDN already sends. No `grep -q`:
# under pipefail it can exit early on a match and SIGPIPE the writer, which reads
# as "no match" on a fast Linux runner.
vary_has_accept() {
  printf '%s' "$F_VARY" | tr ',' '\n' | tr -d ' \t' | tr '[:upper:]' '[:lower:]' | grep -x -e accept -e '\*' >/dev/null
}
is_json() { case $(lc "$F_CTYPE") in *json*) return 0 ;; esac; return 1; }
lc() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# is_challenge: the edge answered with a page meant for a browser. Content-type
# html, a cf-mitigated header, or a 403 whose body is markup.
is_challenge() {
  [ -n "$(hdr cf-mitigated)" ] && return 0
  case $(lc "$F_CTYPE") in *text/html*) return 0 ;; esac
  [ "$F_STATUS" = 403 ] && head -c 200 "$F_BODY" | grep -qi '^[[:space:]]*<' && return 0
  return 1
}
is_ap_json() { case $(lc "$F_CTYPE") in *application/activity+json*|*application/ld+json*) return 0 ;; esac; return 1; }
says_fed_off() { grep -Eqi 'federation_disabled|federation is (switched )?(off|disabled)' "$F_BODY"; }

# discovery LABEL PATH ACCEPT: webfinger / nodeinfo with a federation UA.
discovery() {
  local label=$1 path=$2 accept=$3
  fetch GET "$path" "$accept"
  if [ "$F_STATUS" = 000 ]; then fail "$label: $F_SEEN"
  elif is_challenge; then fail "$label: edge challenges federation clients: HTML answer (challenge or frontend fallback) ($F_SEEN)"
  elif [ "$F_STATUS" = 404 ] || [ "$F_STATUS" = 503 ]; then
    warn "$label: app answered $F_STATUS - federation off, or unknown account ($F_SEEN)"
  elif [ "${F_STATUS:0:1}" = 2 ] || [ "${F_STATUS:0:1}" = 3 ]; then pass "$label ($F_SEEN)"
  else fail "$label: unexpected answer ($F_SEEN)"
  fi
}

# unexplained_404 LABEL: a 404 without the federation_disabled body. It is one of
# three things and the probe cannot tell which, so it fails unless the operator
# says they run a release that answers 404 while federation is off.
unexplained_404() {
  if [ "$PRE503" = 1 ]; then
    warn "$1: 404 - federation off on a release up to v0.7.25, if that is what you run (--pre-503) ($F_SEEN)"
  else
    fail "$1: 404 without the federation_disabled body - an unknown account, edge interference, or federation off on a release up to v0.7.25 (which answered 404; pass --pre-503 if that is yours) ($F_SEEN)"
  fi
}

# object_pair LABEL PATH: the AP representation, then the HTML one, of one URL.
object_pair() {
  local label=$1 path=$2
  fetch GET "$path" 'application/activity+json'
  local ok=0
  if [ "$F_STATUS" = 000 ]; then fail "$label AP GET: $F_SEEN"
  elif is_challenge; then fail "$label AP GET: edge challenges federation clients: HTML answer (challenge or frontend fallback) ($F_SEEN)"
  elif says_fed_off; then
    FED_OFF=1; warn "$label AP GET: federation off ($F_SEEN)"
  elif [ "$F_STATUS" = 404 ]; then
    unexplained_404 "$label AP GET"
  elif { [ "$F_STATUS" = 401 ] || [ "$F_STATUS" = 403 ]; } && is_json; then
    warn "$label AP GET: $F_STATUS with a JSON body - the app wants a signed fetch ($F_SEEN)"
  elif [ "${F_STATUS:0:1}" != 2 ]; then fail "$label AP GET: unexpected answer ($F_SEEN)"
  elif ! is_ap_json; then fail "$label AP GET: not an ActivityPub content-type ($F_SEEN)"
  else
    ok=1
    pass "$label AP GET ($F_SEEN)"
    # Without Vary: Accept a shared cache keys on the URL alone and may hand
    # HTML to a federation peer or the JSON document to a browser.
    if vary_has_accept; then pass "$label Vary includes Accept"
    else fail "$label Vary: Accept missing - a shared cache could serve the wrong representation ($F_SEEN)"; fi
  fi
  [ "$ok" = 1 ] || return 0
  fetch GET "$path" 'text/html'
  if [ "$F_STATUS" = 000 ]; then fail "$label HTML GET: $F_SEEN"
  elif is_ap_json || grep -q '"@context"' "$F_BODY"; then
    fail "$label HTML GET: edge cached the AP representation - an Accept: text/html request got ActivityPub JSON ($F_SEEN)"
  else pass "$label HTML GET does not return the AP body ($F_SEEN)"
  fi
}

log "edge-ap-probe: $BASE (read-only; one unsigned {} POST to /inbox)"

# 1. Discovery.
discovery webfinger "/.well-known/webfinger?resource=acct:${ACCOUNT:-edge-probe-unknown}@$HOST" 'application/jrd+json'
discovery nodeinfo /.well-known/nodeinfo 'application/json'

# 2/3. Actor and video: AP vs HTML representation of the same URL.
if [ -n "$ACCOUNT" ]; then object_pair "actor /accounts/$ACCOUNT" "/accounts/$ACCOUNT"
else warn 'actor checks skipped: pass --account NAME'; fi
if [ -n "$VIDEO" ]; then
  object_pair "video /videos/$VIDEO" "/videos/$VIDEO"
  object_pair "video /videos/watch/$VIDEO" "/videos/watch/$VIDEO"
fi

# 4. Inbox: an unsigned {} POST must be refused BY THE APP (401/400/202),
# not by the edge. The app is expected to reject it; reaching it is the point.
fetch POST /inbox 'application/activity+json' 'application/activity+json' '{}'
if [ "$F_STATUS" = 000 ]; then fail "inbox POST: $F_SEEN"
elif is_challenge; then fail "inbox POST: edge challenges federation clients: HTML answer (challenge or frontend fallback) ($F_SEEN)"
else
  case $F_STATUS in
    401|400|202) pass "inbox POST reached the app ($F_SEEN)" ;;
    503)
      if says_fed_off; then FED_OFF=1; warn "inbox POST: federation is off on this instance ($F_SEEN)"
      else pass "inbox POST reached the origin ($F_SEEN)"; fi ;;
    404) unexplained_404 'inbox POST' ;;
    301|302|303|307|308) fail "inbox POST: edge redirects the inbox ($F_SEEN)" ;;
    403) fail "inbox POST: 403 - blocked by the edge or a WAF rule ($F_SEEN)" ;;
    *) fail "inbox POST: unexpected answer ($F_SEEN)" ;;
  esac
fi

if [ "$FED_OFF" = 1 ]; then
  log 'NOTE  federation is off on this instance: the app refused ActivityPub itself, so the checks above show the edge lets requests THROUGH to it, not that peers could federate. Re-run after enabling federation.'
fi
log "edge-ap-probe: $FAILS FAIL, $WARNS WARN"
[ "$FAILS" -eq 0 ]
