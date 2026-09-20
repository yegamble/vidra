#!/usr/bin/env node
// tests/stack-e2e.mjs — the media + search half of finding F04, over HTTP only.
//
// WHY THIS EXISTS. meta CI's REQUIRED `boot` lane starts the stack with
// TRANSCODING_ENABLED=false and no SEARCH_SERVICE_URL, so a green required set
// proves that the api boots in production mode and that both migration
// one-shots run — and says nothing at all about upload -> real transcode ->
// fetchable HLS -> indexed in vidra-search. This driver walks that chain
// against a live compose stack and asserts every link, so the NON-REQUIRED
// `stack-e2e` lane can fail for a real reason.
//
// WHY IT DOES NOT REUSE tests/release-acceptance.mjs. That harness proves this
// chain far better — a real Chromium decodes the segments and playback is shown
// to advance — but it cannot run on a GitHub runner: it asserts
// COMPOSE_PROJECT_NAME === 'vidra-release-acceptance', shells out with
// cwd:'/opt/vidra', needs Caddy serving https://secure.video.test from a private
// test CA, and requires a fresh UNCLAIMED install. Those are properties of a
// prepared lab host, not of CI. So the small pieces are COPIED (the owner-claim
// flow, the /internal/v1/search HMAC construction) and nothing is imported:
// every input here arrives through the environment and no host path is baked in.
//
// WHAT THIS DELIBERATELY DOES NOT PROVE — do not over-read a green run:
//   * NO BROWSER DECODE. It asserts `#EXTM3U`, a variant playlist, and 200 +
//     non-zero bytes on the init and first media segment. Bytes that arrive are
//     not bytes that decode; a real player is release-acceptance.mjs's job.
//   * The lane runs with rate limiting OFF and malware scanning OFF, so it
//     proves nothing about the shipped limits or about scanning.
//   * It builds the three components from their DEFAULT BRANCHES. It is not a
//     release qualification and touches no published image or digest.
//
// Inputs (all required, all from the environment — see .github/workflows/stack-e2e.yml):
//   VIDRA_BASE_URL          origin of the api                (e.g. http://127.0.0.1:8099)
//   VIDRA_SEARCH_URL        origin of vidra-search           (e.g. http://127.0.0.1:8098)
//   SEARCH_INTERNAL_SECRET  the core<->search shared HMAC secret
//   VIDRA_SETUP_TOKEN       the one-time owner-claim token from the api boot log
//   argv[2] | VIDRA_FIXTURE path to the generated mp4 fixture
import assert from 'node:assert/strict';
import { createHmac, randomBytes } from 'node:crypto';
import { readFileSync } from 'node:fs';

// fetch has been stable since Node 18; the runner ships far newer. Asserting it
// turns "fetch is not defined" into a sentence that names the cause.
assert.ok(Number(process.versions.node.split('.')[0]) >= 18, `Node >= 18 required, got ${process.version}`);

const need = name => {
  const value = (process.env[name] ?? '').trim();
  assert.ok(value, `${name} must be set in the environment`);
  return value;
};
const trimSlash = url => url.replace(/\/+$/, '');
const baseURL = trimSlash(need('VIDRA_BASE_URL'));
const searchURL = trimSlash(need('VIDRA_SEARCH_URL'));
const internalSecret = need('SEARCH_INTERNAL_SECRET');
const setupToken = need('VIDRA_SETUP_TOKEN');
const fixturePath = process.argv[2] ?? need('VIDRA_FIXTURE');
const fixture = readFileSync(fixturePath);
assert.ok(fixture.length > 0, `${fixturePath} is empty — the ffmpeg fixture step did not produce a file`);

const started = Date.now();
const elapsed = () => `${((Date.now() - started) / 1000).toFixed(1)}s`;
const log = (...parts) => console.log(`[stack-e2e ${elapsed()}]`, ...parts);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

// Every failure in this file must be diagnosable from the job log alone: the
// artifact is a postmortem aid, not the first line of defence. So each HTTP
// call that goes wrong reports method, URL, status and the body it got back.
const call = async (url, { method = 'GET', body, token, headers = {}, binary = false } = {}) => {
  const init = { method, headers: { ...headers }, redirect: 'manual' };
  if (token) init.headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) {
    if (Buffer.isBuffer(body)) {
      init.body = body;
      init.headers['Content-Type'] = 'application/octet-stream';
    } else {
      init.body = JSON.stringify(body);
      init.headers['Content-Type'] = 'application/json';
    }
  }
  let response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    throw new Error(`${method} ${url} — transport failure: ${error.message}`);
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  const text = binary ? null : bytes.toString('utf8');
  let json = null;
  if (text !== null) { try { json = JSON.parse(text); } catch { /* not every body is JSON */ } }
  return { status: response.status, headers: response.headers, bytes, text, json };
};

const expectStatus = (result, wanted, what) => {
  const wantedList = Array.isArray(wanted) ? wanted : [wanted];
  assert.ok(
    wantedList.includes(result.status),
    `${what}: expected HTTP ${wantedList.join('/')}, got ${result.status}. Body: ${(result.text ?? '<binary>').slice(0, 800)}`,
  );
  return result;
};

const api = async (path, options = {}) => call(`${baseURL}${path}`, options);

// Bounded polling with a loud timeout. A bare "timed out" tells a reader
// nothing, so the deadline message carries the LAST observation — which is
// almost always the diagnosis (a stuck job state, a missing rendition, an
// event that never left the outbox).
const until = async (label, { deadlineMs, intervalMs = 2000 }, probe) => {
  const deadline = Date.now() + deadlineMs;
  let polls = 0;
  let last = null;
  for (;;) {
    polls += 1;
    last = await probe();
    if (last?.done) {
      log(`${label}: satisfied after ${polls} polls`);
      return last;
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `${label}: TIMED OUT after ${Math.round(deadlineMs / 1000)}s and ${polls} polls. ` +
        `Last observed state: ${JSON.stringify(last, null, 2)}`,
      );
    }
    await sleep(intervalMs);
  }
};

const nonce = randomBytes(5).toString('hex');
const password = `${randomBytes(18).toString('base64url')}A1!`;
const owner = { username: `e2e${nonce}`, email: `e2e${nonce}@example.invalid`, password };
// A distinctive single token: the public search is a trigram match over titles,
// and a generic title would match whatever else the corpus holds.
const title = `Stacke2e${nonce}`;

// ---------------------------------------------------------------- owner claim
log(`claiming the owner account as ${owner.username}`);
const claimed = expectStatus(
  await api('/api/v1/setup/claim-owner', { method: 'POST', body: { token: setupToken, ...owner } }),
  201,
  'owner claim',
).json;
assert.ok(claimed?.token, `owner claim returned no session token: ${JSON.stringify(claimed)}`);
assert.match(claimed.user.id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
log(`owner claimed: user ${claimed.user.id} role=${claimed.user.role}`);

// Log in with the very credentials just created. The claim response's own token
// would work, so this exists to prove the credential round-trips through the
// normal sign-in path and not only through the one-shot bootstrap.
const login = expectStatus(
  await api('/api/v1/auth/login', { method: 'POST', body: { identifier: owner.email, password: owner.password } }),
  200,
  'owner login',
).json;
assert.ok(login?.token, `login returned no token: ${JSON.stringify(login)}`);
assert.equal(login.user.id, claimed.user.id);
const token = login.token;
log('owner logged in through /api/v1/auth/login');

// -------------------------------------------------------------------- channel
// A DIFFERENT prefix from the username on purpose: accounts and channels share
// ONE handle namespace on an instance (ActivityPub gives them one), so reusing
// the owner's username here is a 409 handle_reserved, not a fresh handle.
const handle = `chan${nonce}`;
const channel = expectStatus(
  await api('/api/v1/channels', { method: 'POST', token, body: { handle, display_name: `Stack E2E ${nonce}` } }),
  201,
  'create channel',
).json;
log(`channel created: @${channel.handle} (${channel.id})`);

// ------------------------------------------------------------ draft + upload
// privacy is set explicitly rather than inherited from the instance default:
// only a PUBLIC, PUBLISHED video reaches the search index, and a default that
// changed under us would surface as an unexplained search timeout.
const draft = expectStatus(
  await api(`/api/v1/channels/${encodeURIComponent(handle)}/videos`, {
    method: 'POST',
    token,
    body: { title, description: 'Generated by the stack-e2e CI lane.', privacy: 'public' },
  }),
  201,
  'create draft video',
).json;
const videoID = draft.id;
log(`draft video ${videoID} state=${draft.state} privacy=${draft.privacy}`);

const session = expectStatus(
  await api(`/api/v1/videos/${videoID}/upload-session`, {
    method: 'POST',
    token,
    body: { size: fixture.length, filename: 'stack-e2e.mp4' },
  }),
  201,
  'open upload session',
).json;
log(`upload session ${session.upload_id}: ${fixture.length} bytes in ${session.total_chunks} chunk(s) of ${session.chunk_size}`);
// THE UPLOAD MUST REALLY BE CHUNKED. vidra's only upload API is the resumable
// one, and its contract — "every chunk but the last must be exactly chunk_size
// bytes", then an in-order server-side assembly — is not exercised at all by a
// single-chunk upload. chunk_size is a compile-time 8 MiB constant
// (vidra-core internal/upload/service.go), so the workflow deliberately mints a
// fixture larger than that. If this ever fails, the fixture shrank and the word
// "chunked" stopped being true, which is exactly what it is here to catch.
assert.ok(
  session.total_chunks >= 2,
  `the fixture is ${fixture.length} bytes against a ${session.chunk_size}-byte chunk size, so this upload is ` +
  `${session.total_chunks} chunk(s): the multi-chunk path is NOT being tested. Grow the fixture or stop calling it chunked.`,
);

for (let n = 0; n < session.total_chunks; n += 1) {
  const slice = fixture.subarray(n * session.chunk_size, Math.min((n + 1) * session.chunk_size, fixture.length));
  expectStatus(
    await api(`/api/v1/uploads/${session.upload_id}/chunks/${n}`, { method: 'PUT', token, body: slice }),
    200,
    `PUT chunk ${n}`,
  );
}
// 202 = accepted and queued; 200 = already terminal (this driver never retries,
// so 200 here would mean someone else finished the session).
expectStatus(
  await api(`/api/v1/uploads/${session.upload_id}/complete`, { method: 'POST', token }),
  [200, 202],
  'complete upload',
);
log('upload completed; the finalize job is queued');

const uploadDone = await until('upload finalize', { deadlineMs: 300000 }, async () => {
  const status = expectStatus(
    await api(`/api/v1/uploads/${session.upload_id}`, { token }),
    200,
    'poll upload status',
  ).json;
  assert.notEqual(
    status.state, 'failed',
    `upload finalisation FAILED: ${status.failure_reason || '(no reason given)'} — full status ${JSON.stringify(status)}`,
  );
  assert.notEqual(status.state, 'cancelled', `upload was cancelled: ${JSON.stringify(status)}`);
  return { done: status.state === 'completed', state: status.state, bytes_received: status.bytes_received };
});
log(`upload finalised: ${JSON.stringify(uploadDone)}`);

// --------------------------------------------------------------- transcoding
// THE ASSERTION THE `boot` LANE CANNOT MAKE. ffmpeg really runs here: the api
// image carries it and VIDRA_ROLE=all runs the in-process transcode worker.
// The fixture is 320x240, and PlanHLSLadderWith skips every enabled rung taller
// than the source — so the default {1080,720,480,360} ladder collapses to ONE
// rung at the source's own size. That is how the ladder is pinned low without
// inventing a knob: make the source small.
//
// Every distinct state is recorded so the log shows the transition, not just the
// destination — "it was already published when we first looked" and "it really
// transcoded" are different claims.
const transitions = [];
const video = await until('transcode + publish', { deadlineMs: 600000, intervalMs: 3000 }, async () => {
  const detail = expectStatus(await api(`/api/v1/videos/${videoID}`, { token }), 200, 'poll video detail').json;
  const shape = {
    state: detail.state,
    packaging_format: detail.packaging_format ?? null,
    renditions: detail.renditions ?? null,
    hls_url: detail.hls_url ?? null,
  };
  const fingerprint = JSON.stringify(shape);
  if (transitions.at(-1) !== fingerprint) { transitions.push(fingerprint); log(`  video state -> ${fingerprint}`); }
  assert.notEqual(
    detail.state, 'failed',
    `the video reached state=failed — the transcode or the probe rejected the fixture. Detail: ${JSON.stringify(detail)}`,
  );
  return { done: detail.state === 'published' && Boolean(detail.hls_url) && (detail.renditions?.length ?? 0) > 0, ...shape };
});
assert.equal(video.packaging_format, 'cmaf', `expected CMAF packaging, got ${video.packaging_format}`);
assert.ok(video.renditions.length >= 1, 'the transcode advertised no renditions');
log(`TRANSCODE PROVEN: state=${video.state} packaging=${video.packaging_format} renditions=${JSON.stringify(video.renditions)}`);
log(`  observed transitions (${transitions.length}): ${transitions.join('  ==>  ')}`);

// ----------------------------------------------------------------- HLS bytes
// Anonymous on purpose: a public published video's playlists and segments must
// be reachable without a credential, which is what a player actually does.
const masterURL = new URL(video.hls_url, `${baseURL}/`);
const master = expectStatus(await call(masterURL.href, {}), 200, 'GET the HLS master playlist');
assert.ok(master.text.startsWith('#EXTM3U'), `master playlist is not an HLS playlist. First 200 bytes: ${master.text.slice(0, 200)}`);
log(`master playlist: 200, ${master.bytes.length} bytes, starts with #EXTM3U`);

// A variant URI is the first non-comment line after an #EXT-X-STREAM-INF tag.
const lines = master.text.split('\n').map(line => line.trim());
const variants = lines.filter((line, i) => line && !line.startsWith('#') && (lines[i - 1] ?? '').startsWith('#EXT-X-STREAM-INF'));
assert.ok(variants.length >= 1, `the master playlist advertises no variant. Playlist:\n${master.text}`);
const variantURL = new URL(variants[0], masterURL);
const variant = expectStatus(await call(variantURL.href, {}), 200, `GET the variant playlist ${variants[0]}`);
assert.ok(variant.text.startsWith('#EXTM3U'), `variant playlist is not an HLS playlist. First 200 bytes: ${variant.text.slice(0, 200)}`);
log(`variant playlist ${variants[0]}: 200, ${variant.bytes.length} bytes, ${variants.length} variant(s) advertised`);

const variantLines = variant.text.split('\n').map(line => line.trim());

// A 200 WITH BYTES IS NOT A SEGMENT. `bytes.length > 0` accepts one byte, or an
// HTML error page an upstream proxy substituted. Every ISOBMFF file is a
// sequence of boxes, each `[uint32 size][4-char type]`, so the four bytes at
// offset 4 are the first box's type: that is the cheapest real structural check
// there is, and no error page passes it.
const boxTypeAt4 = bytes => (bytes.length >= 8 ? bytes.toString('latin1', 4, 8) : `<only ${bytes.length} bytes>`);
const assertISOBMFF = (bytes, allowed, minBytes, what) => {
  const type = boxTypeAt4(bytes);
  assert.ok(
    allowed.includes(type),
    `${what}: first ISOBMFF box type is ${JSON.stringify(type)}, expected one of ${allowed.join('/')}. ` +
    `This is not fMP4 — first 32 bytes: ${bytes.subarray(0, 32).toString('hex')}`,
  );
  assert.ok(bytes.length >= minBytes, `${what}: only ${bytes.length} bytes, below the ${minBytes}-byte floor`);
  return type;
};

// CMAF/fMP4 carries an initialisation segment in #EXT-X-MAP; a decoder is
// useless without it, so an empty one is a failure even though the playlist
// parses. TS packaging has no MAP tag, and the lane must not pretend otherwise.
const mapMatch = variant.text.match(/#EXT-X-MAP:[^\n]*URI="([^"]+)"/);
if (mapMatch) {
  const initURL = new URL(mapMatch[1], variantURL);
  const init = expectStatus(await call(initURL.href, { binary: true }), 200, `GET the CMAF init segment ${mapMatch[1]}`);
  // An init segment is `ftyp` then `moov` — it declares the brand and the
  // track, and nothing else can stand in for it.
  const initBox = assertISOBMFF(init.bytes, ['ftyp'], 256, `init segment ${mapMatch[1]}`);
  log(`INIT SEGMENT PROVEN: ${mapMatch[1]}: 200, ${init.bytes.length} bytes, first box '${initBox}'`);
} else {
  log('no #EXT-X-MAP in the variant playlist (not CMAF packaging) — no init segment to fetch');
}

const segments = variantLines.filter((line, i) => line && !line.startsWith('#') && (variantLines[i - 1] ?? '').startsWith('#EXTINF'));
assert.ok(segments.length >= 1, `the variant playlist lists no media segment. Playlist:\n${variant.text}`);
const segmentURL = new URL(segments[0], variantURL);
const segment = expectStatus(await call(segmentURL.href, { binary: true }), 200, `GET the first media segment ${segments[0]}`);
// `styp`, exactly, because that is what this packager emits and it was
// measured, not assumed: run 35505921660 served
// `chunk-0-00001.m4s: 508516 bytes, first box 'styp'`. The packager is
// ffmpeg's dash muxer with `-dash_segment_type mp4` and `movflags=+cmaf`
// (vidra-core internal/media/cmaf.go), and the segment-type box is what the
// `+cmaf` brand requires. A bare `moof` here would still be a legal fMP4
// fragment — which is exactly why it must not pass: it would mean the CMAF
// brand box stopped being written, a real change in what the tree claims to
// be, and one nothing else in CI would notice.
const segmentBox = assertISOBMFF(segment.bytes, ['styp'], 1024, `media segment ${segments[0]}`);
log(`SEGMENT PROVEN: first media segment ${segments[0]}: 200, ${segment.bytes.length} bytes, first box '${segmentBox}' (${segments.length} segment(s) in the variant)`);

// -------------------------------------------------------------------- search
// The load-bearing search proof. /api/v1/videos/search has a LOCAL SQL FALLBACK
// that returns the same result set when the service is unreachable, so the
// public endpoint alone cannot distinguish "vidra-search indexed it" from
// "vidra-search is down and core answered from Postgres". A signed
// /internal/v1/search against the search container can only be answered by
// vidra-search itself, out of its own `search.documents` — so that is asserted
// first, and the public endpoint after it.
//
// The construction is vidra-search's own (internal/api/auth.go InternalSignature):
// hex HMAC-SHA256 over "ts\nMETHOD\nPATH" — the PATH only, never the query.
const signedSearch = async query => {
  const path = '/internal/v1/search';
  const ts = String(Math.floor(Date.now() / 1000));
  const signature = createHmac('sha256', internalSecret).update(`${ts}\nGET\n${path}`).digest('hex');
  const url = new URL(`${searchURL}${path}`);
  url.search = new URLSearchParams({ q: query, limit: '20', offset: '0', mode: 'simple', personalized: 'false' }).toString();
  return call(url.href, { headers: { 'X-Vidra-Internal-Auth': `v1:${ts}:${signature}` } });
};

const indexed = await until('vidra-search indexing', { deadlineMs: 180000 }, async () => {
  const result = await signedSearch(title);
  // 401 here means the HMAC or the shared secret is wrong, not that indexing is
  // slow — retrying it for three minutes would hide the real fault.
  assert.notEqual(result.status, 401, 'vidra-search rejected the internal HMAC — SEARCH_INTERNAL_SECRET disagrees between core and search');
  if (result.status !== 200) return { done: false, status: result.status, body: (result.text ?? '').slice(0, 300) };
  const ids = (result.json?.ids ?? []).map(hit => hit.video_id);
  return { done: ids.includes(videoID), status: result.status, returned_ids: ids };
});
log(`WRITE PATH PROVEN (core -> vidra-search): the signed /internal/v1/search returned ${videoID} out of vidra-search's own index — ${JSON.stringify(indexed)}`);

// THE READ PATH, AND WHY A RETURNED ID IS NOT ENOUGH. handleSearchVideos has
// two backends: vidra-search, and a local SQL trigram fallback it takes on ANY
// search-client error (vidra-core internal/httpapi/videos.go). Both answer the
// identical public contract, and a one-word title matches trigram search
// trivially — so "the id came back" stays green with the service unreachable,
// the breaker open, or the query HMAC wrong. That is the whole integration this
// lane exists to cover, silently untested.
//
// `search_total` and `total_is_lower_bound` are the discriminator. Both are
// filled ONLY from searchServicePaging on the service branch; the SQL branch
// leaves them nil and `omitempty` drops them. vidra-search's own contract makes
// `total_is_lower_bound` REQUIRED and computes `total` unless skip_count is
// asked for (core never asks), so on the service path both are always present.
// No SQL fallback can produce either field.
const publicSearch = await until('public search API', { deadlineMs: 60000 }, async () => {
  const result = await api(`/api/v1/videos/search?q=${encodeURIComponent(title)}&limit=20`);
  if (result.status !== 200) return { done: false, status: result.status, body: (result.text ?? '').slice(0, 300) };
  const ids = (result.json?.videos ?? []).map(entry => entry.id);
  return {
    done: ids.includes(videoID),
    status: result.status,
    returned_ids: ids,
    search_total: result.json?.search_total ?? null,
    total_is_lower_bound: result.json?.total_is_lower_bound ?? null,
    body_keys: Object.keys(result.json ?? {}),
  };
});
assert.notEqual(
  publicSearch.search_total, null,
  'the public search answered with the video but WITHOUT search_total — core served it from its local SQL trigram ' +
  `fallback, not from vidra-search. Response keys: ${JSON.stringify(publicSearch.body_keys)}`,
);
assert.notEqual(
  publicSearch.total_is_lower_bound, null,
  'the public search answered without total_is_lower_bound — vidra-search makes that field mandatory, so this ' +
  `response did not come from it. Response keys: ${JSON.stringify(publicSearch.body_keys)}`,
);
log(`READ PATH PROVEN (browser -> core -> vidra-search): /api/v1/videos/search returned ${videoID} and carries ` +
    `search_total=${publicSearch.search_total} total_is_lower_bound=${publicSearch.total_is_lower_bound}, ` +
    'neither of which the local SQL fallback can produce');

// A SECOND LOOK, AFTER THE QUEUE IS EMPTY — NOT AFTER A GUESSED INTERVAL.
//
// "Indexed" has to mean "still indexed once every queued event has been
// applied", because this lane has already produced the opposite: on run
// 35504619907 the document was suppressed (eligible=false,
// suppressed_reason=reconcile_orphan) 130 ms AFTER the assertion above passed,
// by a reconcile.end that a failed first drain had pushed behind the upsert.
//
// The first attempt at this guard slept 10 s, which was calibrated to nothing:
// a failed drain reschedules at drainBaseBackoff = 30 s, doubling
// (vidra-core internal/searchevents/drainer.go), so a re-delivery cannot arrive
// sooner than ~30 s plus a 5 s tick and a 10 s sleep could only ever pass. A
// longer sleep would be the same mistake with a bigger number, so the condition
// is read instead of waited out: the api exports the outbox depth by state as
// vidra_queue_depth{queue="search_outbox",state=...} (scrape-time, from
// SearchOutboxDepth), and a rescheduled row is still `pending`. Zero pending
// rows means nothing is left to apply.
const outboxPending = async () => {
  const metrics = expectStatus(await api('/metrics'), 200, 'GET /metrics');
  let familySeen = false;
  let pending = 0;
  for (const line of metrics.text.split('\n')) {
    if (!line.startsWith('vidra_queue_depth{')) continue;
    const labelEnd = line.indexOf('}');
    if (labelEnd < 0) continue;
    const labels = Object.fromEntries(
      [...line.slice('vidra_queue_depth{'.length, labelEnd).matchAll(/([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"/g)]
        .map(m => [m[1], m[2]]),
    );
    if (labels.queue !== 'search_outbox') continue;
    familySeen = true;
    if (labels.state === 'pending') pending += Number(line.slice(labelEnd + 1).trim());
  }
  return { familySeen, pending };
};

// GROUP BY produces no row for a state with no rows, so "drained" shows up as
// the `pending` series DISAPPEARING, not as a 0. That makes an absent series
// indistinguishable from an absent METRIC — so the family has to be seen at
// least once (there are always delivered rows to anchor it) or this check would
// pass vacuously against a renamed or disabled gauge. That is the failure this
// whole item is about, so it fails loudly rather than assuming.
const drained = await until('search outbox drains to zero pending', { deadlineMs: 180000, intervalMs: 2000 }, async () => {
  const { familySeen, pending } = await outboxPending();
  return { done: familySeen && pending === 0, family_seen: familySeen, pending_rows: pending };
});
assert.ok(
  drained.family_seen,
  'vidra_queue_depth{queue="search_outbox"} was never exported, so "the queue drained" was never actually observed. ' +
  'Check METRICS_ENABLED and the gauge name before trusting any green from this step.',
);
log(`OUTBOX DRAINED: vidra_queue_depth{queue="search_outbox",state="pending"} is 0 — ${JSON.stringify(drained)}`);

const stillIndexed = await signedSearch(title);
expectStatus(stillIndexed, 200, 're-check /internal/v1/search after the outbox drained');
const stillIDs = (stillIndexed.json?.ids ?? []).map(hit => hit.video_id);
assert.ok(
  stillIDs.includes(videoID),
  'the video was indexed and then DISAPPEARED once the outbox finished draining — vidra-search returned ' +
  `${JSON.stringify(stillIDs)}. Read search.documents.suppressed_reason in the evidence artifact: a late, ` +
  'out-of-order event suppressed it.',
);
log(`SEARCH STILL INDEXED with an empty outbox — ${JSON.stringify(stillIDs)}`);

log(`PASS — upload -> transcode -> HLS bytes -> searchable, video ${videoID}, title ${title}`);
