#!/usr/bin/env node
// tests/peertube-interop/driver.mjs — the scenarios of the PeerTube interop lab.
//
//   node driver.mjs control   PeerTube <-> PeerTube: a follow plus a federated video
//   node driver.mjs vidra     S1-S8 and the gap checks G4-G7, G11, G12, vidra <-> PeerTube v8.3.2
//
// run.sh starts the stack and calls this; it is not meant to be run bare.
//
// WHY THE CONTROL EXISTS. Every vidra scenario below rides on a private CA, DNS
// aliases on a Docker network and a TLS edge. Break any of those and all eight
// scenarios fail looking like vidra bugs. `control` makes two STOCK PeerTube
// instances do the same dance through the same edge with the same helpers, so
// a red vidra scenario after a green control is about vidra (or about how the
// driver talks to vidra) and not about the lab.
//
// HOW IT REACHES THE APPS. The lab publishes exactly one port, the edge, on
// 127.0.0.1. The lab's names (*.interop.test) resolve only inside the Docker
// network, so every request here dials 127.0.0.1:<edge port> and presents the
// app's name as TLS SNI and as Host, trusting only the lab CA. That is why this
// file uses node:https and not fetch: fetch cannot dial one address while
// verifying a certificate for another name.
//
// A SCENARIO THAT FAILS DOES NOT STOP THE RUN. The point of the lab is the
// whole table: a red check is a finding, and stopping at the first one would
// hide every later result. Each scenario
// records pass / fail / blocked plus the UTC window it ran in, so the matching
// PeerTube and vidra log lines can be cut out of out/logs/ afterwards.
// `blocked` is not `fail`: it means a step this scenario DEPENDS on never
// happened, so the scenario measured nothing.
//
// WHAT THIS DELIBERATELY DOES NOT PROVE — do not over-read a green run:
//   * NOTHING ABOUT SSRF. Both sides run with their private-address guard off.
//   * NOTHING ABOUT THE REAL EDGE. No Cloudflare, no WAF, no public DNS, no
//     ACME; the shipped Caddyfile's routing is real, its TLS is not.
//   * ONE BROWSER, ONE CLIP. G7 plays a single 4 s video in headless Chrome
//     on this machine. Every other "PeerTube can play it" is playlist text
//     plus segment bytes fetched from the URLs PeerTube stored.
//
// Inputs (environment, all set by run.sh):
//   EDGE_PORT, LAB_CA_FILE, LAB_OUT, LAB_FIXTURE, LAB_COMPOSE_FILE,
//   PT_ROOT_PASSWORD, and for `vidra`: OWNER_CLAIM_TOKEN, LAB_VIDRA_PROJECT,
//   LAB_FIXTURE_AUDIO, LAB_FIXTURE_NODURATION; optionally LAB_CHROME
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createHash, createSign, randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import https from 'node:https';
import tls from 'node:tls';

assert.ok(Number(process.versions.node.split('.')[0]) >= 18, `Node >= 18 required, got ${process.version}`);

const need = name => {
  const value = (process.env[name] ?? '').trim();
  assert.ok(value, `${name} must be set in the environment (run this through run.sh)`);
  return value;
};
const mode = process.argv[2];
assert.ok(['control', 'vidra'].includes(mode), 'usage: driver.mjs control|vidra');
const edgePort = Number(need('EDGE_PORT'));
const ca = readFileSync(need('LAB_CA_FILE'));
const outDir = need('LAB_OUT');
const fixture = readFileSync(need('LAB_FIXTURE'));
const labCompose = need('LAB_COMPOSE_FILE');
const ptRootPassword = need('PT_ROOT_PASSWORD');
assert.ok(fixture.length > 0, 'the fixture is empty');

const PT = 'pt.interop.test';
const CTL = 'ctl.interop.test';
const VIDRA = 'vidra.interop.test';
const REDIR = 'redir.interop.test';

const started = Date.now();
const elapsed = () => `${((Date.now() - started) / 1000).toFixed(1)}s`;
const log = (...parts) => console.log(`[pt-interop ${mode} ${elapsed()}]`, ...parts);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const nonce = randomBytes(4).toString('hex');

// One request to one lab app, through the edge. Never follows a redirect: a
// 3xx is an observation here, not something to paper over.
const call = (host, path, { method = 'GET', body, token, headers = {}, binary = false } = {}) =>
  new Promise((resolve, reject) => {
    const h = { Host: host, ...headers };
    let payload;
    if (token) h.Authorization = `Bearer ${token}`;
    if (body !== undefined) {
      if (Buffer.isBuffer(body)) {
        payload = body;
        h['Content-Type'] ??= 'application/octet-stream';
      } else if (typeof body === 'string') {
        payload = Buffer.from(body);
      } else {
        payload = Buffer.from(JSON.stringify(body));
        h['Content-Type'] ??= 'application/json';
      }
      h['Content-Length'] = payload.length;
    }
    const req = https.request(
      { host: '127.0.0.1', port: edgePort, servername: host, ca, method, path, headers: h, timeout: 60000 },
      res => {
        const chunks = [];
        res.on('data', c => chunks.push(c));
        res.on('end', () => {
          const bytes = Buffer.concat(chunks);
          const text = binary ? null : bytes.toString('utf8');
          let json = null;
          if (text !== null) { try { json = JSON.parse(text); } catch { /* not every body is JSON */ } }
          resolve({ status: res.statusCode, headers: res.headers, bytes, text, json });
        });
      },
    );
    req.on('timeout', () => req.destroy(new Error('timed out after 60s')));
    req.on('error', error => reject(new Error(`${method} https://${host}${path} — transport failure: ${error.message}`)));
    if (payload) req.write(payload);
    req.end();
  });

// Fetch an absolute lab URL the way a remote peer would name it.
const callURL = (href, options) => {
  const url = new URL(href);
  assert.ok(url.hostname.endsWith('.interop.test'), `refusing to leave the lab: ${href}`);
  return call(url.hostname, `${url.pathname}${url.search}`, options);
};

const expectStatus = (result, wanted, what) => {
  const wantedList = Array.isArray(wanted) ? wanted : [wanted];
  assert.ok(
    wantedList.includes(result.status),
    `${what}: expected HTTP ${wantedList.join('/')}, got ${result.status}. Body: ${(result.text ?? '<binary>').slice(0, 800)}`,
  );
  return result;
};

// Bounded polling with a loud timeout that carries the LAST observation —
// almost always the diagnosis (a follow stuck in `pending`, an empty list).
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
        `Last observed state: ${JSON.stringify(last)}`,
      );
    }
    await sleep(intervalMs);
  }
};

// The inverse of `until`, for assertions of ABSENCE ("the edit must not have
// propagated" is only meaningful after waiting long enough for it to).
const holdsFor = async (label, { windowMs, intervalMs = 2000 }, probe) => {
  const deadline = Date.now() + windowMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await probe();
    if (last?.changed) return { held: false, ...last };
    await sleep(intervalMs);
  }
  log(`${label}: unchanged for ${Math.round(windowMs / 1000)}s`);
  return { held: true, ...last };
};

const docker = (args, input) =>
  execFileSync('docker', args, { input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], maxBuffer: 256 * 1024 * 1024 });
const labPsql = (service, sql) =>
  docker(['compose', '-f', labCompose, 'exec', '-T', service, 'psql', '-U', 'peertube', '-d', 'peertube', '-At', '-c', sql]).trim();

// PeerTube says WHY it dropped an object only in its debug log, and a red
// check has to carry that line. An entry starts `[host:443] date time level:`
// and may run over many lines (the refused object, pretty-printed).
const logEntries = (service, since) => {
  const raw = docker(['compose', '-f', labCompose, 'logs', '--no-color', '--no-log-prefix', '--since', since, service]);
  const entries = [];
  for (const line of raw.split('\n')) {
    if (/^\[[^\]]+\] \d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} \w+: /.test(line)) entries.push({ line: line.replace(/ \{$/, ''), body: '' });
    else if (entries.length > 0) entries[entries.length - 1].body += `${line}\n`;
  }
  return entries;
};
// The lines PeerTube logged when it refused something that names `needle`.
const peertubeSaid = (service, since, needle) =>
  logEntries(service, since)
    .filter(e => /is not valid|Cannot process activity/.test(e.line) && (e.line.includes(needle) || e.body.includes(needle)))
    .map(e => e.line)
    .slice(0, 4);

// ------------------------------------------------------------ PeerTube client
const multipart = fields => {
  const boundary = `----ptinterop${randomBytes(12).toString('hex')}`;
  const parts = [];
  for (const [name, value] of Object.entries(fields)) {
    if (value && value.bytes) {
      parts.push(Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="${name}"; filename="${value.filename}"\r\n` +
        `Content-Type: ${value.type}\r\n\r\n`,
      ), value.bytes, Buffer.from('\r\n'));
    } else {
      parts.push(Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n${value}\r\n`));
    }
  }
  parts.push(Buffer.from(`--${boundary}--\r\n`));
  return { body: Buffer.concat(parts), type: `multipart/form-data; boundary=${boundary}` };
};

const peertube = async host => {
  const client = expectStatus(await call(host, '/api/v1/oauth-clients/local'), 200, `${host} oauth client`).json;
  const form = new URLSearchParams({
    client_id: client.client_id, client_secret: client.client_secret,
    grant_type: 'password', response_type: 'code', username: 'root', password: ptRootPassword,
  }).toString();
  const grant = expectStatus(
    await call(host, '/api/v1/users/token', { method: 'POST', body: form, headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }),
    200, `${host} root login`,
  ).json;
  const token = grant.access_token;
  const me = expectStatus(await call(host, '/api/v1/users/me', { token }), 200, `${host} /users/me`).json;
  const channel = me.videoChannels[0];
  assert.ok(channel?.id, `${host}: root has no default channel: ${JSON.stringify(me.videoChannels)}`);
  const self = {
    host, token, channel, account: me.account,
    get: (path, options = {}) => call(host, path, { token, ...options }),
    post: (path, body, options = {}) => call(host, path, { method: 'POST', token, body, ...options }),
    put: (path, body, options = {}) => call(host, path, { method: 'PUT', token, body, ...options }),
    del: (path, options = {}) => call(host, path, { method: 'DELETE', token, ...options }),
    // waitTranscoding=false: the video is published (and federated) from its
    // source file at once, so a slow transcode cannot masquerade as a
    // federation delay.
    upload: async (name, channelId = channel.id) => {
      const form = multipart({
        channelId, name, privacy: 1, waitTranscoding: 'false',
        videofile: { filename: 'interop-fixture.mp4', type: 'video/mp4', bytes: fixture },
      });
      const result = expectStatus(
        await call(host, '/api/v1/videos/upload', { method: 'POST', token, body: form.body, headers: { 'Content-Type': form.type } }),
        200, `${host} upload "${name}"`,
      ).json;
      return result.video;
    },
    followInstance: async target => expectStatus(
      await self.post('/api/v1/server/following', { hosts: [target] }), 204, `${host} follows instance ${target}`,
    ),
    following: async () => expectStatus(await self.get('/api/v1/server/following?count=100'), 200, `${host} following`).json.data,
    followers: async () => expectStatus(await self.get('/api/v1/server/followers?count=100'), 200, `${host} followers`).json.data,
    // A remote video is addressable by its uuid on an instance that received it.
    video: uuid => self.get(`/api/v1/videos/${uuid}`),
  };
  return self;
};

// ---------------------------------------------------------- scenario runner
const results = [];
const scenario = async (id, title, body) => {
  const from = new Date().toISOString();
  log(`---- ${id}: ${title}`);
  const record = { id, title, verdict: 'pass', from, to: null, checks: [], error: null };
  // A check that fails is recorded and the scenario carries on to the next
  // one: S7 and S8 are several independent claims each, and the first red must
  // not hide the rest.
  const check = async (name, fn) => {
    try {
      const detail = await fn();
      record.checks.push({ name, verdict: 'pass', detail: detail ?? null });
      log(`  PASS  ${name}`);
      return true;
    } catch (error) {
      const blocked = error instanceof Blocked;
      record.checks.push({ name, verdict: blocked ? 'blocked' : 'fail', detail: error.message });
      if (blocked) { if (record.verdict === 'pass') record.verdict = 'blocked'; } else record.verdict = 'fail';
      log(`  ${blocked ? 'BLOCKED' : 'FAIL'}  ${name}: ${error.message}`);
      return false;
    }
  };
  // An OBSERVATION is a measurement the plan asks for (a G-row) that is not
  // part of the scenario's own pass/fail claim. It is recorded with what was
  // seen and never changes a verdict: "PeerTube's older videos did not arrive"
  // is a fact about G11, not a failure of "the follow was accepted".
  const observe = async (name, fn) => {
    let detail;
    try { detail = await fn(); } catch (error) { detail = { error: error.message }; }
    record.checks.push({ name, verdict: 'observed', detail });
    log(`  OBSERVED  ${name}: ${JSON.stringify(detail)}`);
    return detail;
  };
  try {
    await body(check, observe);
  } catch (error) {
    record.verdict = error instanceof Blocked ? (record.verdict === 'fail' ? 'fail' : 'blocked') : 'fail';
    record.error = error.message;
    log(`  ${record.verdict.toUpperCase()}  ${id} aborted: ${error.message}`);
  }
  record.to = new Date().toISOString();
  log(`---- ${id}: ${record.verdict.toUpperCase()}`);
  results.push(record);
  return record;
};
class Blocked extends Error {}
const blockedUnless = (condition, why) => { if (!condition) throw new Blocked(why); };

const finish = () => {
  const file = `${outDir}/results-${mode}.json`;
  writeFileSync(file, `${JSON.stringify({ mode, nonce, finished: new Date().toISOString(), results }, null, 2)}\n`);
  console.log('');
  console.log(`| scenario | verdict | title |`);
  console.log(`|---|---|---|`);
  for (const r of results) console.log(`| ${r.id} | ${r.verdict.toUpperCase()} | ${r.title} |`);
  console.log(`\nwritten: ${file}`);
  process.exit(results.every(r => r.verdict === 'pass') ? 0 : 1);
};

// ==================================================================== control
const runControl = async () => {
  const pt = await peertube(PT);
  const ctl = await peertube(CTL);
  log(`logged in to both PeerTubes as root (pt channel ${pt.channel.name}, ctl channel ${ctl.channel.name})`);
  let uploaded = null;

  await scenario('C1', 'ctl follows the pt instance; pt accepts', async check => {
    await ctl.followInstance(PT);
    await check('ctl lists pt as following, state accepted', async () => {
      const seen = await until('ctl following pt', { deadlineMs: 90000 }, async () => {
        const row = (await ctl.following()).find(f => f.following?.host === PT);
        return { done: row?.state === 'accepted', state: row?.state ?? null };
      });
      return seen;
    });
    await check('pt lists ctl as a follower, state accepted', async () => {
      const row = (await pt.followers()).find(f => f.follower?.host === CTL);
      assert.equal(row?.state, 'accepted', `pt's followers: ${JSON.stringify(row ?? null)}`);
      return { state: row.state };
    });
  });

  await scenario('C2', 'a video uploaded to pt arrives on ctl as a remote video', async check => {
    const name = `Control video ${nonce}`;
    uploaded = await pt.upload(name);
    log(`  pt accepted the upload: uuid ${uploaded.uuid}`);
    await check('ctl serves the video by uuid, isLocal=false, name intact', async () => {
      const seen = await until('video on ctl', { deadlineMs: 120000 }, async () => {
        const got = await ctl.video(uploaded.uuid);
        return { done: got.status === 200, status: got.status, name: got.json?.name ?? null, isLocal: got.json?.isLocal ?? null };
      });
      assert.equal(seen.name, name);
      assert.equal(seen.isLocal, false);
      return seen;
    });
  });

  // The reference for S7: what a STOCK PeerTube does when the origin makes a
  // video private. Whatever vidra does with the same two activities (PeerTube
  // sends a Delete and then an Update) is compared against this.
  await scenario('C3', 'a video made private on pt disappears from ctl', async check => {
    blockedUnless(uploaded, 'C2 uploaded nothing');
    await check('ctl answers 404 for it after the privacy flip', async () => {
      expectStatus(await pt.put(`/api/v1/videos/${uploaded.uuid}`, { privacy: 3 }), 204, 'pt makes the video private');
      return until('video gone from ctl', { deadlineMs: 60000 }, async () => {
        const got = await ctl.video(uploaded.uuid);
        return { done: got.status === 404, status: got.status };
      });
    });
    // Put it back: the vidra run's G11 observation counts pt's public videos.
    await check('made public again, it returns to ctl', async () => {
      expectStatus(await pt.put(`/api/v1/videos/${uploaded.uuid}`, { privacy: 1 }), 204, 'pt makes the video public again');
      return until('video back on ctl', { deadlineMs: 60000 }, async () => {
        const got = await ctl.video(uploaded.uuid);
        return { done: got.status === 200, status: got.status };
      });
    });
  });
};

// ====================================================================== vidra
const vidraProject = () => need('LAB_VIDRA_PROJECT');
const vidraPsql = sql =>
  docker(['compose', '-p', vidraProject(), 'exec', '-T', 'postgres', 'psql', '-U', 'vidra', '-d', 'vidra', '-At', '-c', sql]).trim();
const sqlText = value => `'${String(value).replace(/'/g, "''")}'`;

const vidraClient = async () => {
  const password = `${randomBytes(18).toString('base64url')}A1!`;
  const owner = { username: `lab${nonce}`, email: `lab${nonce}@example.invalid`, password };
  const claimed = expectStatus(
    await call(VIDRA, '/api/v1/setup/claim-owner', { method: 'POST', body: { token: need('OWNER_CLAIM_TOKEN'), ...owner } }),
    201, 'vidra owner claim',
  ).json;
  const token = claimed.token;
  assert.ok(token, `owner claim returned no token: ${JSON.stringify(claimed)}`);
  const api = (path, options = {}) => call(VIDRA, path, { token, ...options });
  const self = {
    owner, token, api,
    createChannel: async handle => expectStatus(
      await api('/api/v1/channels', { method: 'POST', body: { handle, display_name: `Interop ${handle}` } }), 201, `create channel ${handle}`,
    ).json,
    // The same resumable flow tests/stack-e2e.mjs proves, minus its assertions:
    // here it is a means, and a failure in it is a harness-level Blocked.
    // `source`, `privacy` and `needHls` exist for the gap checks, which need an
    // upload vidra gives no poster or no duration, or one nothing federates
    // until the driver says so. Every S-scenario takes the defaults.
    publish: async (handle, title, { source = { bytes: fixture, filename: 'interop-fixture.mp4' }, privacy = 'public', needHls = true } = {}) => {
      const draft = expectStatus(
        await api(`/api/v1/channels/${encodeURIComponent(handle)}/videos`, { method: 'POST', body: { title, description: `Interop lab ${nonce}`, privacy } }),
        201, `create draft "${title}"`,
      ).json;
      const session = expectStatus(
        await api(`/api/v1/videos/${draft.id}/upload-session`, { method: 'POST', body: { size: source.bytes.length, filename: source.filename } }),
        201, 'open upload session',
      ).json;
      for (let n = 0; n < session.total_chunks; n += 1) {
        const slice = source.bytes.subarray(n * session.chunk_size, Math.min((n + 1) * session.chunk_size, source.bytes.length));
        expectStatus(await api(`/api/v1/uploads/${session.upload_id}/chunks/${n}`, { method: 'PUT', body: slice }), 200, `PUT chunk ${n}`);
      }
      expectStatus(await api(`/api/v1/uploads/${session.upload_id}/complete`, { method: 'POST' }), [200, 202], 'complete upload');
      const video = await until(`vidra transcode + publish "${title}"`, { deadlineMs: 300000, intervalMs: 3000 }, async () => {
        const detail = expectStatus(await api(`/api/v1/videos/${draft.id}`), 200, 'poll video').json;
        assert.notEqual(detail.state, 'failed', `vidra video reached state=failed: ${JSON.stringify(detail)}`);
        return { done: detail.state === 'published' && (!needHls || Boolean(detail.hls_url)), state: detail.state, hls_url: detail.hls_url ?? null };
      });
      return { id: draft.id, title, hls_url: video.hls_url, object_url: `https://${VIDRA}/videos/${draft.id}` };
    },
    patch: (id, body) => api(`/api/v1/videos/${id}`, { method: 'PATCH', body }),
    setPoster: (id, bytes, filename) => {
      const form = multipart({ file: { filename, type: 'image/jpeg', bytes } });
      return api(`/api/v1/videos/${id}/thumbnail`, { method: 'POST', body: form.body, headers: { 'Content-Type': form.type } });
    },
    // The object a remote server is given for a video: anonymous, and through
    // the shipped Caddyfile's Accept routing, exactly as PeerTube fetches it.
    object: id => call(VIDRA, `/videos/${id}`, { headers: { Accept: 'application/activity+json' } }),
    // vidra has no "list remote videos" REST route to poll, so the store is
    // read directly: a row here is what "vidra received it" means.
    remoteVideo: objectURL => {
      const row = vidraPsql(
        `select id || '|' || title || '|' || remote_actor_url from remote_videos where object_url = ${sqlText(objectURL)}`,
      );
      if (!row) return null;
      const [id, title, actor] = row.split('|');
      return { id, title, remote_actor_url: actor };
    },
  };
  return self;
};

// PeerTube's own row for a remote object, by its ActivityPub id — the second
// opinion when the REST API says 404 (it also says 404 for a blacklisted or
// private row, which is a different fact from "never stored").
const ptVideoRow = (dbService, objectURL) =>
  labPsql(dbService, `select uuid || '|' || name || '|' || privacy from video where url = ${sqlText(objectURL)}`) || null;

const ptFollowState = (dbService, targetActorURL) =>
  labPsql(dbService,
    `select af.state from "actorFollow" af join actor t on t.id = af."targetActorId" where t.url = ${sqlText(targetActorURL)}`) || null;

// A cavage rsa-sha256 signature over `(request-target) host date digest` — the
// exact profile PeerTube sends and vidra's httpsig verifies. The private key
// is a REAL PeerTube actor's, read out of the lab PeerTube's own database, so
// the baseline request is indistinguishable from PeerTube's and each negative
// differs from it in exactly one property.
const signedPost = async (path, bodyBuffer, { keyId, privateKey, date = new Date(), sentBody = bodyBuffer, omitSignature = false }) => {
  const digest = `SHA-256=${createHash('sha256').update(bodyBuffer).digest('base64')}`;
  const dateHeader = date.toUTCString();
  const signingString = [`(request-target): post ${path}`, `host: ${VIDRA}`, `date: ${dateHeader}`, `digest: ${digest}`].join('\n');
  const signature = createSign('RSA-SHA256').update(signingString).sign(privateKey, 'base64');
  const headers = { 'Content-Type': 'application/activity+json', Date: dateHeader, Digest: digest };
  if (!omitSignature) {
    headers.Signature = `keyId="${keyId}",algorithm="rsa-sha256",headers="(request-target) host date digest",signature="${signature}"`;
  }
  return call(VIDRA, path, { method: 'POST', body: sentBody, headers });
};

// vidra's own access log, for the status it answered an inbound activity with.
const vidraInboxStatuses = since => {
  const counts = {};
  for (const line of docker(['compose', '-p', vidraProject(), 'logs', '--no-color', '--no-log-prefix', '--since', since, 'api']).split('\n')) {
    let entry = null;
    try { entry = JSON.parse(line); } catch { continue; }
    if (entry.msg === 'request' && entry.method === 'POST' && /\/inbox$/.test(entry.path ?? '')) counts[entry.status] = (counts[entry.status] ?? 0) + 1;
  }
  return counts;
};

// ------------------------------------------------------------------ browser
// G7 asks whether a PeerTube user can PLAY a vidra video, and that needs a real
// player and a real decoder. Chrome is driven over its DevTools pipe
// (--remote-debugging-pipe: NUL-terminated JSON on fd 3 and fd 4), so the lab
// still installs nothing. Two flags make the lab reachable from it and nothing
// else: every *.interop.test name is mapped to the edge's loopback port while
// every other name fails to resolve, and the certificates the edge presents
// are accepted by their public-key hashes — "trust the lab CA" without
// touching this machine's trust store.
const chromeBinary = () => [
  process.env.LAB_CHROME,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].find(path => path && existsSync(path)) ?? null;

const edgeKeyHashes = async hosts => {
  const hashes = new Set();
  for (const host of hosts) {
    await new Promise((resolve, reject) => {
      const socket = tls.connect({ host: '127.0.0.1', port: edgePort, servername: host, ca }, () => {
        let cert = socket.getPeerX509Certificate();
        for (let depth = 0; cert && depth < 4; depth += 1) {
          hashes.add(createHash('sha256').update(cert.publicKey.export({ type: 'spki', format: 'der' })).digest('base64'));
          cert = cert.issuerCertificate;
        }
        socket.end();
        resolve();
      });
      socket.on('error', reject);
    });
  }
  return [...hashes];
};

const openBrowser = async () => {
  const binary = chromeBinary();
  blockedUnless(binary, 'no Chrome or Chromium on this machine (set LAB_CHROME to a binary), so nothing was played');
  const profile = `${outDir}/chrome-profile`;
  rmSync(profile, { recursive: true, force: true });
  mkdirSync(profile, { recursive: true });
  const child = spawn(binary, [
    '--headless=new', '--remote-debugging-pipe', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-extensions', '--mute-audio',
    '--autoplay-policy=no-user-gesture-required',
    `--host-resolver-rules=MAP *.interop.test 127.0.0.1:${edgePort}, MAP * ~NOTFOUND`,
    `--ignore-certificate-errors-spki-list=${(await edgeKeyHashes([PT, VIDRA])).join(',')}`,
    'about:blank',
  ], { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  const pending = new Map();
  const listeners = [];
  let nextId = 0;
  let buffered = '';
  let gone = null;
  child.on('exit', code => {
    gone = new Error(`the browser exited (code ${code})`);
    for (const waiter of pending.values()) waiter.reject(gone);
    pending.clear();
  });
  child.stdio[4].setEncoding('utf8');
  child.stdio[4].on('data', chunk => {
    buffered += chunk;
    for (let cut = buffered.indexOf('\0'); cut >= 0; cut = buffered.indexOf('\0')) {
      const message = JSON.parse(buffered.slice(0, cut));
      buffered = buffered.slice(cut + 1);
      const waiter = pending.get(message.id);
      if (waiter) {
        pending.delete(message.id);
        clearTimeout(waiter.timer);
        if (message.error) waiter.reject(new Error(`${waiter.method}: ${message.error.message}`)); else waiter.resolve(message.result);
      } else if (message.method) {
        for (const listener of listeners) listener(message);
      }
    }
  });
  const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    if (gone) { reject(gone); return; }
    nextId += 1;
    const id = nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method}: no answer from the browser in 30 s`)); }, 30000);
    pending.set(id, { resolve, reject, method, timer });
    child.stdio[3].write(`${JSON.stringify({ id, method, params, sessionId })}\0`);
  });
  const version = (await send('Browser.getVersion')).product;
  return {
    version, send,
    on: listener => listeners.push(listener),
    close: async () => {
      await Promise.race([send('Browser.close').catch(() => {}), sleep(3000)]);
      if (!gone) child.kill('SIGKILL');
      rmSync(profile, { recursive: true, force: true });
    },
  };
};

// Load PeerTube's own watch page for a video and report what its player did:
// the title it shows, and (with `play`) what the <video> element went through.
const watchOnPeerTube = async (host, uuid, { play }) => {
  const browser = await openBrowser();
  try {
    const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await browser.send('Target.attachToTarget', { targetId, flatten: true });
    const page = (method, params) => browser.send(method, params, sessionId);
    const seen = { sockets: [], outside: new Set(), fromVidra: {}, failed: [], errors: [] };
    const urls = new Map();
    browser.on(({ method, params }) => {
      if (method === 'Network.requestWillBeSent') {
        urls.set(params.requestId, params.request.url);
        const target = new URL(params.request.url);
        if (/^(https?|wss?):$/.test(target.protocol) && !target.hostname.endsWith('.interop.test')) seen.outside.add(target.host);
      } else if (method === 'Network.responseReceived') {
        const target = new URL(params.response.url);
        if (target.hostname === VIDRA) {
          const key = `${params.response.status} ${target.pathname.replace(/[0-9a-f-]{36}/, '<id>').replace(/\d+/g, 'N')}`;
          seen.fromVidra[key] = (seen.fromVidra[key] ?? 0) + 1;
        }
      } else if (method === 'Network.loadingFailed') {
        seen.failed.push(`${params.errorText} ${(urls.get(params.requestId) ?? '').slice(0, 140)}`);
      } else if (method === 'Network.webSocketCreated') {
        seen.sockets.push(params.url);
        const target = new URL(params.url);
        if (!target.hostname.endsWith('.interop.test')) seen.outside.add(target.host);
      } else if (method === 'Runtime.exceptionThrown') {
        seen.errors.push(`exception: ${(params.exceptionDetails.exception?.description ?? params.exceptionDetails.text).slice(0, 300)}`);
      } else if (method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(params.type)) {
        seen.errors.push(`console.${params.type}: ${params.args.map(a => a.value ?? a.description ?? '').join(' ').slice(0, 300)}`);
      } else if (method === 'Log.entryAdded' && ['error', 'warning'].includes(params.entry.level)) {
        seen.errors.push(`log.${params.entry.level}: ${params.entry.text.slice(0, 300)}`);
      }
    });
    for (const domain of ['Page', 'Runtime', 'Network', 'Log']) await page(`${domain}.enable`);
    // PeerTube's player opens WebRTC peer connections for P2P. Count them.
    await page('Page.addScriptToEvaluateOnNewDocument', {
      source: `window.__labPeers = []; for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection']) { const Native = window[name];
        if (Native) window[name] = new Proxy(Native, { construct(target, args) { const peer = new target(...args); window.__labPeers.push(peer); return peer; } }); }`,
    });
    await page('Page.navigate', { url: `https://${host}/w/${uuid}` });
    const evaluate = async (expression, options = {}) =>
      (await page('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, ...options })).result.value;
    const report = { browser: browser.version, url: `https://${host}/w/${uuid}`, title: null, playback: null };
    // The title as the page shows it: `text` is the raw text node, `rendered`
    // is what the layout draws (innerText applies the CSS white-space rules).
    const titleDeadline = Date.now() + 60000;
    while (!report.title && Date.now() < titleDeadline) {
      report.title = await evaluate(`(() => { const h = document.querySelector('h1');
        return h && h.textContent.trim() ? { text: h.textContent, rendered: h.innerText, document_title: document.title } : null; })()`);
      if (!report.title) await sleep(500);
    }
    if (play) {
      const sample = `(() => { const v = document.querySelector('video'); if (!v) return null; const q = v.getVideoPlaybackQuality();
        return { t: v.currentTime, ready: v.readyState, paused: v.paused, ended: v.ended, w: v.videoWidth, h: v.videoHeight, frames: q.totalVideoFrames,
          dropped: q.droppedVideoFrames, error: v.error ? v.error.code + ': ' + v.error.message : null, src: v.currentSrc.slice(0, 48) }; })()`;
      const samples = [];
      const deadline = Date.now() + 90000;
      let firstSeen = null;
      let pressedPlay = null;
      while (Date.now() < deadline) {
        const now = await evaluate(sample);
        if (now) {
          firstSeen ??= Date.now();
          samples.push(now);
          const advanced = Math.max(...samples.map(s => s.t)) - Math.min(...samples.map(s => s.t));
          if (now.error || now.ended || (advanced >= 2 && now.frames > 0)) break;
          // A player that is waiting for a click gets one, as a user would give.
          if (pressedPlay === null && now.paused && now.t === 0 && Date.now() - firstSeen > 10000) {
            pressedPlay = await evaluate(`document.querySelector('video').play().then(() => 'played', e => String(e))`, { userGesture: true });
          }
        }
        await sleep(250);
      }
      if (samples.length > 0) {
        const last = samples[samples.length - 1];
        report.playback = {
          samples: samples.length, ready_state_max: Math.max(...samples.map(s => s.ready)),
          current_time_from: Math.min(...samples.map(s => s.t)), current_time_to: Math.max(...samples.map(s => s.t)),
          decoded_frames: Math.max(...samples.map(s => s.frames)), dropped_frames: last.dropped, video_size: `${last.w}x${last.h}`,
          media_error: samples.map(s => s.error).find(Boolean) ?? null, ended: last.ended, pressed_play: pressedPlay, src: last.src,
        };
        // PeerTube's player shows either its P2P counters or an HTTP-fallback
        // label in one control (.vjs-peertube); which one is displayed is the
        // player's own statement of whether it is using P2P.
        report.p2p = {
          peer_connections: await evaluate(`window.__labPeers.map(peer => ({ state: peer.connectionState, made_an_offer: Boolean(peer.localDescription) }))`),
          websockets: seen.sockets, hosts_outside_the_lab_asked_for: [...seen.outside],
          player_control: await evaluate(`(() => { const el = document.querySelector('.vjs-peertube'); if (!el) return null;
            const shown = el.querySelector('.vjs-peertube-displayed');
            return { displayed: shown ? shown.innerText.replace(/\\s+/g, ' ').trim() : null, p2p_counters_displayed: Boolean(shown && shown.querySelector('.peers-number')) }; })()`),
        };
      }
    }
    report.requests_answered_by_vidra = seen.fromVidra;
    report.failed_requests = seen.failed.slice(0, 12);
    report.page_errors = seen.errors.slice(0, 12);
    return report;
  } finally {
    await browser.close();
  }
};

const runVidra = async () => {
  const pt = await peertube(PT);
  const ctl = await peertube(CTL);
  const vidra = await vidraClient();
  log(`vidra owner claimed (${vidra.owner.username}); logged in to pt and ctl as root`);
  const handle = `chan${nonce}`;
  await vidra.createChannel(handle);
  const channelActor = `https://${VIDRA}/video-channels/${handle}`;
  const instanceActor = `https://${VIDRA}/accounts/peertube`;
  const ptChannelHandle = `${pt.channel.name}@${PT}`;
  const ptObjectURL = uuid => `https://${PT}/videos/watch/${uuid}`;

  // What later scenarios depend on. null = the step never happened.
  const state = { s1: false, s2Video: null, s4: false, s5Video: null, s6: false, shortVideo: null };
  // Uploads vidra treats differently from the 4 s mp4: one with no frame to
  // grab a poster from, one with no duration for its probe to read. run.sh
  // makes both.
  const audioFixture = readFileSync(need('LAB_FIXTURE_AUDIO'));
  const noDurationFixture = readFileSync(need('LAB_FIXTURE_NODURATION'));

  const arrivesOnPeerTube = (instance, label, video, deadlineMs = 90000) =>
    until(`${label} on ${instance.host}`, { deadlineMs }, async () => {
      const got = await instance.video(video.id);
      return { done: got.status === 200, status: got.status, name: got.json?.name ?? null };
    });
  const arrivesOnVidra = (label, objectURL, deadlineMs = 90000) =>
    until(`${label} on vidra`, { deadlineMs }, async () => {
      const row = vidra.remoteVideo(objectURL);
      return { done: Boolean(row), row };
    });
  const goneFromPeerTube = (instance, label, video, deadlineMs = 60000) =>
    until(`${label} removed from ${instance.host}`, { deadlineMs }, async () => {
      const got = await instance.video(video.id);
      return { done: got.status === 404, status: got.status, name: got.json?.name ?? null };
    });
  const goneFromVidra = (label, objectURL, deadlineMs = 60000) =>
    until(`${label} removed from vidra`, { deadlineMs }, async () => {
      const row = vidra.remoteVideo(objectURL);
      return { done: !row, row };
    });

  // The gap checks G4 and G6 ask "does PeerTube store it?" of a video whose
  // object lacks something PeerTube's validator wants. First the proof that
  // vidra really served such an object (otherwise the check measured an
  // ordinary video and is BLOCKED, not passed); then PeerTube's answer, and
  // when the answer is no, PeerTube's own row and its own log line.
  const vidraObject = async (video, isTheCase, describe) => {
    const got = await vidra.object(video.id);
    blockedUnless(got.status === 200 && got.json, `vidra does not serve the object for ${video.id} (HTTP ${got.status}), so the case was not produced`);
    blockedUnless(isTheCase(got.json), `vidra's object is not the case this check is about: ${describe(got.json)}`);
    return got.json;
  };
  const storedByPeerTube = async (video, since, served, deadlineMs = 60000) => {
    try {
      await arrivesOnPeerTube(pt, `"${video.title}"`, video, deadlineMs);
    } catch {
      assert.fail(
        `PeerTube answers ${(await pt.video(video.id)).status} for it ${deadlineMs / 1000} s after vidra federated it. ` +
        `What vidra served: ${JSON.stringify(served)}. PeerTube's row: ${JSON.stringify(ptVideoRow('pt-db', video.object_url))}. ` +
        `PeerTube logged: ${JSON.stringify(peertubeSaid('pt', since, video.id))}`,
      );
    }
    const got = (await pt.video(video.id)).json;
    return { vidra_served: served, peertube_stored: { name: got.name, duration: got.duration, thumbnails: (got.thumbnails ?? []).map(t => `${t.width}x${t.height}`) } };
  };
  // G11: did a video that was on PeerTube BEFORE vidra's follow reach vidra?
  // PeerTube never pushes it. vidra has to read the followed actor's outbox,
  // and PeerTube logs every such read — so a red check can say whether vidra
  // asked and got nothing, or never asked.
  const backfilled = async (label, early, since, outboxPath) => {
    try {
      return (await arrivesOnVidra(label, early.objectURL)).row;
    } catch (error) {
      const reads = logEntries('pt', since).filter(e => e.line.includes(`Receiving outbox request for https://${PT}${outboxPath}`)).length;
      return assert.fail(
        `${error.message}. PeerTube logged ${reads} read(s) of ${outboxPath} since vidra asked to follow. It holds ` +
        `${labPsql('pt-db', 'select count(*) from video where remote = false and privacy = 1')} public local videos; vidra holds ` +
        `${vidraPsql(`select count(*) from remote_videos where object_url like ${sqlText(`https://${PT}/%`)}`)} of them.`,
      );
    }
  };

  // ------------------------------------------------------------------- S1
  await scenario('S1', 'PeerTube admin follows the vidra instance', async check => {
    await check('PeerTube accepts the follow request for vidra.interop.test', async () => {
      await pt.followInstance(VIDRA);
    });
    const accepted = await check('PeerTube lists vidra as following, state accepted', async () =>
      until('pt following vidra', { deadlineMs: 90000 }, async () => {
        const row = (await pt.following()).find(f => f.following?.host === VIDRA);
        return { done: row?.state === 'accepted', state: row?.state ?? null, following: row?.following?.name ?? null };
      }));
    await check('vidra has an accepted instance_followers row for pt', async () => {
      const list = expectStatus(await vidra.api('/api/v1/admin/federation/instance-followers'), 200, 'list instance followers').json;
      const row = (list.follows ?? []).find(f => f.host === PT);
      assert.equal(row?.state, 'accepted', `vidra instance followers: ${JSON.stringify(list.follows ?? null)}`);
      const stored = vidraPsql(`select state from instance_followers where remote_actor_url like ${sqlText(`https://${PT}/%`)}`);
      assert.equal(stored, 'accepted', `instance_followers row state is ${JSON.stringify(stored)}`);
      return { rest: row, table: stored };
    });
    state.s1 = accepted;
  });

  // ------------------------------------------------------------------- S2
  await scenario('S2', 'vidra publishes; PeerTube lists it as remote and its media is fetchable', async check => {
    blockedUnless(state.s1, 'S1 did not establish the instance follow, so PeerTube has no reason to receive anything');
    const video = await vidra.publish(handle, `Vidra to PeerTube ${nonce}`);
    log(`  vidra published ${video.id}`);
    let onPT = null;
    const arrived = await check('PeerTube serves the vidra video by uuid', async () => {
      await arrivesOnPeerTube(pt, 'S2 video', video);
      onPT = (await pt.video(video.id)).json;
      return { uuid: onPT.uuid, url: onPT.url };
    });
    if (!arrived) {
      // Not found by uuid: say whether PeerTube stored it under another uuid or
      // never stored it — the difference between an id mismatch and a rejection.
      log(`  pt's own row for ${video.object_url}: ${JSON.stringify(ptVideoRow('pt-db', video.object_url))}`);
      throw new Blocked('the video never arrived on PeerTube, so its fields and media could not be checked');
    }
    state.s2Video = video;
    await check('fields match: name, isLocal=false, duration, channel and account on vidra', async () => {
      assert.equal(onPT.name, video.title);
      assert.equal(onPT.isLocal, false);
      assert.equal(onPT.channel?.host, VIDRA, `channel: ${JSON.stringify(onPT.channel)}`);
      assert.equal(onPT.channel?.name, handle);
      assert.equal(onPT.account?.host, VIDRA, `account: ${JSON.stringify(onPT.account)}`);
      assert.ok(onPT.duration >= 3 && onPT.duration <= 5, `duration ${onPT.duration}s for a 4 s fixture`);
      return { name: onPT.name, duration: onPT.duration, channel: `${onPT.channel.name}@${onPT.channel.host}`, account: `${onPT.account.name}@${onPT.account.host}` };
    });
    // PeerTube 8.3.2's REST shape: `thumbnails[].fileUrl` on /lazy-static, which
    // PeerTube fills by fetching vidra's `icon` on first request. (thumbnailPath,
    // the pre-8 field, is null for local videos too — reading it failed this
    // check on the first run for a reason that had nothing to do with vidra.)
    await check('PeerTube holds a thumbnail for it and can fetch the image from vidra', async () => {
      const thumbnail = onPT.thumbnails?.[0];
      assert.ok(thumbnail?.fileUrl, `no thumbnails[].fileUrl: ${JSON.stringify(onPT.thumbnails ?? null)}`);
      const image = expectStatus(await callURL(thumbnail.fileUrl, { binary: true }), 200, 'GET the thumbnail from PeerTube');
      assert.ok(image.bytes.length > 1000, `thumbnail is ${image.bytes.length} bytes`);
      return { fileUrl: thumbnail.fileUrl, width: thumbnail.width, height: thumbnail.height, bytes: image.bytes.length };
    });
    await check('the HLS playlist PeerTube stored is fetchable: master, variant, first segment', async () => {
      // vidra announces a video when it is published and sends the playable
      // url in an Update once its ladder exists; in between PeerTube holds a
      // copy with no playlist. Reading that copy ONCE made this check pass or
      // fail on where vidra's delivery tick fell
      // (docs/evidence/peertube-interop-2026-11-17.md). So PeerTube's copy is
      // re-read for up to 60 s until it carries a playlist, and then exactly
      // what was asserted before is asserted. A copy that never gets one
      // still fails, on the first assertion below.
      const waitFrom = Date.now();
      let reads = 0;
      for (;;) {
        reads += 1;
        const again = await pt.video(video.id);
        if (again.status === 200) onPT = again.json;
        if (onPT.streamingPlaylists?.[0]?.playlistUrl || Date.now() - waitFrom >= 60000) break;
        await sleep(2000);
      }
      const playlistWaitMs = Date.now() - waitFrom;
      log(`  PeerTube's copy ${onPT.streamingPlaylists?.[0]?.playlistUrl ? 'carries a playlist' : 'still has no playlist'} after ${playlistWaitMs} ms (${reads} reads)`);
      const playlist = onPT.streamingPlaylists?.[0];
      assert.ok(playlist?.playlistUrl, `PeerTube stored no streaming playlist: ${JSON.stringify(onPT.streamingPlaylists)} files=${JSON.stringify(onPT.files)}`);
      const master = expectStatus(await callURL(playlist.playlistUrl), 200, 'GET master playlist');
      assert.ok(master.text.startsWith('#EXTM3U'), `not a playlist: ${master.text.slice(0, 120)}`);
      const lines = master.text.split('\n').map(l => l.trim());
      const variants = lines.filter((l, i) => l && !l.startsWith('#') && (lines[i - 1] ?? '').startsWith('#EXT-X-STREAM-INF'));
      assert.ok(variants.length >= 1, `no variant in the master playlist:\n${master.text}`);
      const variantURL = new URL(variants[0], playlist.playlistUrl);
      const variant = expectStatus(await callURL(variantURL.href), 200, 'GET variant playlist');
      const vlines = variant.text.split('\n').map(l => l.trim());
      const segments = vlines.filter((l, i) => l && !l.startsWith('#') && (vlines[i - 1] ?? '').startsWith('#EXTINF'));
      assert.ok(segments.length >= 1, `no segment in the variant playlist:\n${variant.text}`);
      const segment = expectStatus(await callURL(new URL(segments[0], variantURL).href, { binary: true }), 200, 'GET first segment');
      assert.ok(segment.bytes.length >= 1024, `first segment is only ${segment.bytes.length} bytes`);
      return {
        playlist_wait_ms: playlistWaitMs, playlist_wait_reads: reads,
        playlistUrl: playlist.playlistUrl, variants: variants.length, first_segment_bytes: segment.bytes.length,
        // G7: what PeerTube built from an HLS link whose `tag` is empty.
        peertube_playlist: { files: playlist.files?.length ?? 0, segmentsSha256Url: playlist.segmentsSha256Url ?? null },
        web_video_files: onPT.files?.length ?? 0,
      };
    });
    // G5: PeerTube's VIDEOS.NAME minimum is 3 characters. Until 2026-11-17 this
    // was an observation; it is a check now, with the same 45 s.
    await check('G5: a vidra video with a 2-character title appears on PeerTube', async () => {
      const since = new Date().toISOString();
      const short = await vidra.publish(handle, 'ab');
      try {
        await arrivesOnPeerTube(pt, 'short-title video', short, 45000);
      } catch {
        assert.fail(
          `PeerTube answers ${(await pt.video(short.id)).status} for it 45 s after publish. PeerTube's row: ` +
          `${JSON.stringify(ptVideoRow('pt-db', short.object_url))}. PeerTube logged: ${JSON.stringify(peertubeSaid('pt', since, short.id))}`,
        );
      }
      state.shortVideo = short;
      const name = (await pt.video(short.id)).json.name;
      // The exact string PeerTube holds, code point by code point: whatever
      // vidra padded the title with shows here and on no page.
      return {
        vidra_title: 'ab', peertube_name: name,
        peertube_name_code_points: [...name].map(c => `U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}`),
      };
    });
  });

  // ------------------------------------------------------------------- S3
  // On `ctl`, not `pt`: ctl has no instance follow with vidra, so the channel
  // subscription is its ONLY link and whatever arrives arrived because of it.
  // On pt the S1 instance follow already delivers every public video.
  await scenario('S3', 'a PeerTube user follows a vidra channel; backfill arrives', async check => {
    const subscribed = await check('PeerTube (ctl) accepts the subscription request', async () => {
      expectStatus(await ctl.post('/api/v1/users/me/subscriptions', { uri: `${handle}@${VIDRA}` }), 204, 'ctl subscribes');
    });
    blockedUnless(subscribed, 'ctl refused the subscription request');
    const accepted = await check('the follow reaches state accepted in ctl', async () =>
      until('ctl -> vidra channel follow', { deadlineMs: 90000 }, async () => {
        const followState = ptFollowState('ctl-db', channelActor);
        return { done: followState === 'accepted', state: followState };
      }));
    await check('vidra records the remote follower', async () => {
      const n = vidraPsql(`select count(*) from remote_follows where remote_actor_url like ${sqlText(`https://${CTL}/%`)}`);
      assert.ok(Number(n) >= 1, `remote_follows rows for ctl: ${n}`);
      return { remote_follows_rows: Number(n) };
    });
    blockedUnless(accepted, 'the follow was never accepted, so neither backfill nor delivery can be measured');
    await check('backfill: the video published BEFORE the follow arrives on ctl', async () => {
      blockedUnless(state.s2Video, 'S2 published no video, so there is nothing to backfill');
      return arrivesOnPeerTube(ctl, 'pre-follow video', state.s2Video);
    });
    await check('a video published AFTER the follow arrives on ctl', async () => {
      const video = await vidra.publish(handle, `Vidra after channel follow ${nonce}`);
      return arrivesOnPeerTube(ctl, 'post-follow video', video);
    });
  });

  // ------------------------------------------------------------------- S4
  await scenario('S4', 'a vidra user follows a PeerTube channel', async check => {
    // G11: a public video on the channel BEFORE vidra follows it. PeerTube
    // pushes only new activity, so only a read of the channel's outbox can
    // bring this one to vidra.
    let early = null;
    try {
      const uploaded = await pt.upload(`PeerTube before channel follow ${nonce}`);
      early = { uuid: uploaded.uuid, objectURL: ptObjectURL(uploaded.uuid) };
    } catch (error) { log(`  could not stage the pre-follow video: ${error.message}`); }
    const followedAt = new Date().toISOString();
    const created = await check('vidra accepts the follow request and resolves the channel', async () => {
      const follow = expectStatus(
        await vidra.api('/api/v1/me/remote-follows', { method: 'POST', body: { handle: ptChannelHandle } }), 201, 'vidra follows the pt channel',
      ).json;
      return follow;
    });
    blockedUnless(created, 'vidra could not create the remote follow');
    state.s4 = await check('the follow reaches state accepted on vidra', async () =>
      until('vidra -> pt channel follow', { deadlineMs: 90000 }, async () => {
        const list = expectStatus(await vidra.api('/api/v1/me/remote-follows'), 200, 'list remote follows').json;
        const row = (list.follows ?? []).find(f => f.domain === PT);
        return { done: row?.state === 'accepted', state: row?.state ?? null, handle: row?.handle ?? null };
      }));
    await check('PeerTube lists vidra as a follower of the channel', async () => {
      const followState = labPsql('pt-db',
        `select af.state from "actorFollow" af join actor f on f.id = af."actorId" where f.url like ${sqlText(`https://${VIDRA}/%`)} and af.state = 'accepted' limit 1`);
      assert.equal(followState, 'accepted', `no accepted actorFollow from a vidra actor in pt: ${JSON.stringify(followState)}`);
    });
    // G11. Until 2026-11-17 this was an observation (a count, 30 s after the
    // Accept). It is a check now, on one named video, with the 90 s every
    // other arrival on vidra is given.
    await check('G11: a public video PeerTube published BEFORE the channel follow arrives on vidra', async () => {
      blockedUnless(state.s4, 'the channel follow was never accepted, so there is nothing to backfill from');
      blockedUnless(early, 'no video could be uploaded to pt before the follow');
      return backfilled('pre-channel-follow video', early, followedAt, `/video-channels/${pt.channel.name}/outbox`);
    });
  });

  // ------------------------------------------------------------------- S5
  await scenario('S5', 'PeerTube uploads; the video appears on vidra under the channel name', async check => {
    blockedUnless(state.s4, 'S4 did not establish the channel follow, so vidra would refuse the Create');
    const uploaded = await pt.upload(`PeerTube to vidra ${nonce}`);
    const objectURL = ptObjectURL(uploaded.uuid);
    let row = null;
    const arrived = await check('vidra stores the remote video', async () => {
      row = (await arrivesOnVidra('S5 video', objectURL)).row;
      return row;
    });
    blockedUnless(arrived, 'the video never arrived on vidra, so how it is shown could not be checked');
    state.s5Video = { uuid: uploaded.uuid, id: uploaded.id, objectURL };
    let view = null;
    await check('vidra serves it: title, domain and a stream URL', async () => {
      view = expectStatus(await call(VIDRA, `/api/v1/remote-videos/${row.id}`), 200, 'GET remote video').json;
      assert.equal(view.title, `PeerTube to vidra ${nonce}`);
      assert.equal(view.domain, PT);
      assert.ok(view.stream_url || view.watch_url, `no stream or watch URL: ${JSON.stringify(view)}`);
      return { title: view.title, domain: view.domain, stream_url: view.stream_url ?? null, has_thumbnail: view.has_thumbnail };
    });
    // G9: PeerTube's attributedTo is [Person, Group]. The video belongs to the
    // CHANNEL (Group) root_channel, uploaded by the ACCOUNT (Person) root.
    await check('it is shown under the channel (root_channel), not the uploading account (root)', async () => {
      blockedUnless(view, 'the remote video view could not be read');
      assert.equal(
        view.channel_handle, ptChannelHandle,
        `channel_handle=${JSON.stringify(view.channel_handle)} actor_url=${JSON.stringify(view.actor_url)} ` +
        `account_actor_url=${JSON.stringify(view.account_actor_url)} stored remote_actor_url=${JSON.stringify(row.remote_actor_url)}`,
      );
      return { channel_handle: view.channel_handle, actor_url: view.actor_url };
    });
  });

  // ------------------------------------------------- S7, PeerTube -> vidra (1)
  // BEFORE S6 on purpose: at this point vidra's only edge to pt is the S4
  // CHANNEL follow, which is the state plan gap G10 is about. After S6 the
  // instance follow would accept the same Update for a different reason.
  await scenario('S7b', 'PeerTube -> vidra with only a channel follow: edit, delete', async check => {
    blockedUnless(state.s5Video, 'S5 put no PeerTube video on vidra, so there is nothing to edit or delete');
    await check('an edit on PeerTube reaches vidra', async () => {
      const newName = `PeerTube edited ${nonce}`;
      expectStatus(await pt.put(`/api/v1/videos/${state.s5Video.uuid}`, { name: newName }), 204, 'pt edits the video');
      return until('edited title on vidra', { deadlineMs: 60000 }, async () => {
        const row = vidra.remoteVideo(state.s5Video.objectURL);
        return { done: row?.title === newName, title: row?.title ?? null, wanted: newName };
      });
    });
    await check('a delete on PeerTube removes the copy from vidra', async () => {
      const doomed = await pt.upload(`PeerTube delete me ${nonce}`);
      const objectURL = ptObjectURL(doomed.uuid);
      try { await arrivesOnVidra('delete-me video', objectURL); } catch (error) { throw new Blocked(`the video never arrived on vidra: ${error.message}`); }
      expectStatus(await pt.del(`/api/v1/videos/${doomed.uuid}`), 204, 'pt deletes the video');
      return goneFromVidra('deleted video', objectURL);
    });
  });

  // ------------------------------------------------------------------ G12
  // BEFORE S6, like S7b: vidra's only edge to pt is the S4 channel follow, so
  // exactly one vidra inbox is in the audience of that channel's videos. A
  // user of a THIRD server (ctl) comments on a pt video; pt forwards ctl's
  // activity to the video's audience. The POST is signed by pt and the
  // activity inside it is ctl's: vidra has no way to check who wrote it.
  //
  // What PeerTube does with a refusal (v8.3.2, read from the image): a non-2xx
  // puts the inbox in a bad-inbox set (`Updating N good actor follows and M bad
  // actor follows.`); every 20 HOURS the set is applied, -1000 from a base of
  // 5000 to each follow whose inbox had a failure and no success in that
  // window; a follow at 0 is deleted. A run cannot wait 20 hours, so the check
  // is on the set and the score is recorded beside it.
  await scenario('G12', 'PeerTube forwards a third party\'s activity (a ctl comment on a pt video) to vidra', async (check, observe) => {
    blockedUnless(state.s5Video, 'S5 put no PeerTube video on vidra, so there is nothing for a third party to comment on');
    const followScores = () => labPsql('pt-db',
      `select string_agg(f.url || ' -> ' || t.url || ' ' || af.state || ' score=' || af.score, '; ' order by af.id) from "actorFollow" af ` +
      `join actor f on f.id = af."actorId" join actor t on t.id = af."targetActorId" where f.url like ${sqlText(`https://${VIDRA}/%`)}`);
    const scoresBefore = followScores();
    const since = new Date().toISOString();
    const comments = 5;
    const posted = await check(`a ctl user posts ${comments} comments on the pt video, and pt receives them`, async () => {
      await until('the pt video on ctl', { deadlineMs: 60000 }, async () => {
        const got = await ctl.video(state.s5Video.uuid);
        return { done: got.status === 200, status: got.status };
      });
      for (let n = 1; n <= comments; n += 1) {
        expectStatus(
          await ctl.post(`/api/v1/videos/${state.s5Video.uuid}/comment-threads`, { text: `G12 third-party comment ${n} ${nonce}` }), 200, `ctl posts comment ${n}`,
        );
        await sleep(1500);
      }
      return until('the comments on pt', { deadlineMs: 60000 }, async () => {
        const total = (await pt.get(`/api/v1/videos/${state.s5Video.uuid}/comment-threads`)).json?.total ?? 0;
        return { done: total >= comments, comments_on_pt: total };
      });
    });
    blockedUnless(posted, 'the third-party comments never reached pt, so pt had nothing to forward');
    let measured = null;
    const forwarded = await check('PeerTube forwards each comment to a vidra inbox', async () => {
      const answered = await until('forwards answered by vidra', { deadlineMs: 60000 }, async () => {
        const statuses = vidraInboxStatuses(since);
        return { done: Object.values(statuses).reduce((a, b) => a + b, 0) >= comments, statuses };
      });
      await sleep(3000); // PeerTube logs the outcome of a broadcast after the last answer
      const entries = logEntries('pt', since);
      const jobs = entries.filter(e => e.line.includes('Creating forwarding job.') && e.body.includes(`https://${VIDRA}/`));
      assert.ok(jobs.length >= comments, `pt created ${jobs.length} forwarding job(s) naming a vidra inbox for ${comments} comments`);
      const failures = entries.filter(e => e.line.includes(`HTTP broadcast to https://${VIDRA}/`) && e.line.includes('failed'));
      const marked = entries.filter(e => / bad actor follows\./.test(e.line) && e.body.includes(`https://${VIDRA}/`));
      measured = {
        forwarding_jobs: jobs.length,
        vidra_answered: answered.statuses,
        peertube_failed_broadcasts: failures.length,
        peertube_saw_status: [...new Set(failures.map(e => /"statusCode": (\d+)/.exec(e.body)?.[1] ?? 'unknown'))],
        peertube_marked_the_inbox_bad: marked.length,
        peertube_lines: [...failures.slice(0, 1), ...marked.slice(0, 1)].map(e => e.line),
      };
      return measured;
    });
    await check('G12: vidra answers every forwarded activity 2xx, so PeerTube marks no vidra inbox bad', async () => {
      blockedUnless(forwarded && measured, 'pt forwarded nothing to vidra, so nothing was measured');
      const refused = Object.keys(measured.vidra_answered).filter(status => !/^2\d\d$/.test(status));
      assert.ok(refused.length === 0 && measured.peertube_marked_the_inbox_bad === 0, JSON.stringify(measured));
      return measured;
    });
    await observe('G12: PeerTube\'s follow rows for vidra, before and after the forwards', async () => ({
      before: scoresBefore, after: followScores(),
      note: 'PeerTube v8.3.2 applies its bad-inbox set to actorFollow.score every 20 hours, so a score cannot move within a run',
    }));
  });

  // ------------------------------------------------------------------- S6
  let ptSecondChannel = null;
  await scenario('S6', 'vidra admin follows the PeerTube instance; a new upload arrives by Announce', async check => {
    // G11: a public video on a channel vidra does NOT follow, uploaded BEFORE
    // the instance follow. Nothing delivers it to vidra (the 10 s below is
    // there to show that), so only a read of pt's instance outbox can.
    let early = null;
    try {
      const made = expectStatus(
        await pt.post('/api/v1/video-channels', { name: `early_${nonce}`, displayName: `Early ${nonce}` }), 200, 'pt creates the pre-follow channel',
      ).json;
      const uploaded = await pt.upload(`PeerTube before instance follow ${nonce}`, made.videoChannel.id);
      early = { uuid: uploaded.uuid, objectURL: ptObjectURL(uploaded.uuid) };
      await sleep(10000);
      early.heldBeforeFollow = Boolean(vidra.remoteVideo(early.objectURL));
    } catch (error) { log(`  could not stage the pre-follow video: ${error.message}`); }
    const followedAt = new Date().toISOString();
    const created = await check('vidra accepts the instance follow request', async () =>
      expectStatus(
        await vidra.api('/api/v1/admin/federation/instance-following', { method: 'POST', body: { host: PT } }), 201, 'vidra follows the pt instance',
      ).json);
    blockedUnless(created, 'vidra could not create the instance follow');
    state.s6 = await check('the follow reaches state accepted on vidra', async () =>
      until('vidra -> pt instance follow', { deadlineMs: 90000 }, async () => {
        const list = expectStatus(await vidra.api('/api/v1/admin/federation/instance-following'), 200, 'list instance following').json;
        const row = (list.follows ?? []).find(f => f.host === PT);
        return { done: row?.state === 'accepted', state: row?.state ?? null };
      }));
    await check('PeerTube lists vidra as an instance follower, state accepted', async () => {
      const row = (await pt.followers()).find(f => f.follower?.host === VIDRA && f.following?.name === 'peertube');
      assert.equal(row?.state, 'accepted', `pt followers from vidra: ${JSON.stringify((await pt.followers()).filter(f => f.follower?.host === VIDRA))}`);
      return { follower: `${row.follower.name}@${row.follower.host}` };
    });
    blockedUnless(state.s6, 'the instance follow was never accepted');
    // A channel vidra does NOT follow: whatever arrives from it arrived through
    // the instance follow (PeerTube's instance-actor Announce), not through S4.
    await check('an upload to a pt channel vidra does not follow arrives on vidra', async () => {
      const made = expectStatus(
        await pt.post('/api/v1/video-channels', { name: `second_${nonce}`, displayName: `Second ${nonce}` }), 200, 'pt creates a second channel',
      ).json;
      ptSecondChannel = { id: made.videoChannel.id, name: `second_${nonce}` };
      const uploaded = await pt.upload(`PeerTube via instance follow ${nonce}`, ptSecondChannel.id);
      const seen = await arrivesOnVidra('instance-follow video', ptObjectURL(uploaded.uuid));
      return seen.row;
    });
    await check('G11: a public video PeerTube published BEFORE the instance follow arrives on vidra', async () => {
      blockedUnless(early, 'no video could be uploaded to pt before the follow');
      blockedUnless(!early.heldBeforeFollow, 'vidra already held the video before the instance follow, so its presence would prove nothing');
      return backfilled('pre-instance-follow video', early, followedAt, '/accounts/peertube/outbox');
    });
  });

  // ------------------------------------------------- S7, PeerTube -> vidra (2)
  await scenario('S7c', 'PeerTube -> vidra with an instance follow: edit, privacy flip, moderator block', async check => {
    blockedUnless(state.s6, 'S6 did not establish the instance follow');
    const fresh = async label => {
      const uploaded = await pt.upload(`PeerTube ${label} ${nonce}`);
      const objectURL = ptObjectURL(uploaded.uuid);
      try { await arrivesOnVidra(`${label} video`, objectURL); } catch (error) { throw new Blocked(`the video never arrived on vidra: ${error.message}`); }
      return { uuid: uploaded.uuid, objectURL };
    };
    await check('an edit on PeerTube reaches vidra', async () => {
      const video = await fresh('edit-2');
      const newName = `PeerTube edited twice ${nonce}`;
      expectStatus(await pt.put(`/api/v1/videos/${video.uuid}`, { name: newName }), 204, 'pt edits the video');
      return until('edited title on vidra', { deadlineMs: 60000 }, async () => {
        const row = vidra.remoteVideo(video.objectURL);
        return { done: row?.title === newName, title: row?.title ?? null, wanted: newName };
      });
    });
    await check('a flip to private on PeerTube removes the copy from vidra', async () => {
      const video = await fresh('privacy');
      expectStatus(await pt.put(`/api/v1/videos/${video.uuid}`, { privacy: 3 }), 204, 'pt makes the video private');
      return goneFromVidra('now-private video', video.objectURL);
    });
    // The privacy flip above is a RACE, not a constant: it failed on one full
    // run and passed on the next. When the flip lands while PeerTube is still
    // transcoding, PeerTube sends its Delete and then an Update for the same
    // video. So the flip is repeated, as fast as the video arrives, and each
    // repetition records what vidra and the stock PeerTube (ctl, which follows
    // pt and gets the same two activities) are left holding.
    await check('privacy flip repeated 5 times: no copy is left on vidra (the stock PeerTube keeps none)', async () => {
      const rounds = [];
      for (let n = 1; n <= 5; n += 1) {
        const video = await fresh(`privacy-${n}`);
        expectStatus(await pt.put(`/api/v1/videos/${video.uuid}`, { privacy: 3 }), 204, 'pt makes the video private');
        await sleep(12000);
        rounds.push({ uuid: video.uuid, on_vidra: Boolean(vidra.remoteVideo(video.objectURL)), ctl_status: (await ctl.video(video.uuid)).status });
      }
      const summary = { left_on_vidra: rounds.filter(r => r.on_vidra).length, left_on_ctl: rounds.filter(r => r.ctl_status === 200).length, rounds };
      // Asserted, not merely observed: a video its owner made PRIVATE that stays
      // listed on vidra is a failure of S7 whichever way the single flip above
      // happened to land.
      assert.equal(summary.left_on_vidra, 0, JSON.stringify(summary));
      return summary;
    });
    await check('a moderator block (unfederate) on PeerTube removes the copy from vidra', async () => {
      const video = await fresh('blacklist');
      expectStatus(
        await pt.post(`/api/v1/videos/${video.uuid}/blacklist`, { reason: 'interop lab', unfederate: true }), 204, 'pt blacklists the video',
      );
      return goneFromVidra('blacklisted video', video.objectURL);
    });
  });

  // ---------------------------------------------------- S7, vidra -> PeerTube
  await scenario('S7a', 'vidra -> PeerTube: edit, privacy flip, delete, moderator block', async check => {
    blockedUnless(state.s1, 'S1 did not establish the instance follow');
    const fresh = async label => {
      const video = await vidra.publish(handle, `Vidra ${label} ${nonce}`);
      try { await arrivesOnPeerTube(pt, `${label} video`, video); } catch (error) { throw new Blocked(`the video never arrived on PeerTube: ${error.message}`); }
      return video;
    };
    await check('an edit on vidra reaches PeerTube', async () => {
      const video = await fresh('edit');
      const newTitle = `Vidra edited ${nonce}`;
      expectStatus(await vidra.api(`/api/v1/videos/${video.id}`, { method: 'PATCH', body: { title: newTitle } }), 200, 'vidra edits the video');
      return until('edited name on pt', { deadlineMs: 60000 }, async () => {
        const got = await pt.video(video.id);
        return { done: got.json?.name === newTitle, status: got.status, name: got.json?.name ?? null, wanted: newTitle };
      });
    });
    await check('a flip to private on vidra removes the copy from PeerTube', async () => {
      const video = await fresh('privacy');
      expectStatus(await vidra.api(`/api/v1/videos/${video.id}`, { method: 'PATCH', body: { privacy: 'private' } }), 200, 'vidra makes the video private');
      return goneFromPeerTube(pt, 'now-private video', video);
    });
    await check('a delete on vidra removes the copy from PeerTube', async () => {
      const video = await fresh('delete');
      expectStatus(await vidra.api(`/api/v1/videos/${video.id}`, { method: 'DELETE' }), [200, 204], 'vidra deletes the video');
      return goneFromPeerTube(pt, 'deleted video', video);
    });
    await check('a moderator block on vidra removes the copy from PeerTube', async () => {
      const video = await fresh('block');
      expectStatus(
        await vidra.api(`/api/v1/admin/videos/${video.id}/block`, { method: 'POST', body: { reason: 'interop lab' } }), [200, 201, 204], 'vidra blocks the video',
      );
      return goneFromPeerTube(pt, 'blocked video', video);
    });
  });

  // ------------------------------------------------------------------- G4
  // PeerTube refuses a whole video that has no valid icon, and an icon without
  // an integer width and height is not valid (v8.3.2 misc.js setValidRemoteIcon,
  // videos.js "icons"). vidra leaves the icon out when a video has no poster
  // and leaves the size out when it cannot read it. Both cases are produced
  // through vidra's own API: nothing is edited in its database or its storage.
  // These run after S1-S7 so the objects they put in vidra's outbox cannot
  // change what the scenarios before them measured.
  await scenario('G4', 'vidra videos with no poster, and with a poster of unreadable size: does PeerTube store them', async check => {
    blockedUnless(state.s1, 'S1 did not establish the instance follow, so PeerTube has no reason to receive anything');
    // vidra grabs no frame from an audio-only source (video/service.go), so
    // the upload is published with no poster at all.
    await check('G4a: an audio-only upload, which vidra publishes with no poster, is stored by PeerTube', async () => {
      const since = new Date().toISOString();
      let video = null;
      try {
        video = await vidra.publish(handle, `Vidra audio only ${nonce}`, { source: { bytes: audioFixture, filename: 'interop-audio.m4a' }, needHls: false });
      } catch (error) { throw new Blocked(`vidra did not publish the audio-only upload: ${error.message}`); }
      const object = await vidraObject(video, o => o.icon === undefined, o => `it carries an icon: ${JSON.stringify(o.icon)}`);
      return storedByPeerTube(video, since, { icon: object.icon ?? null, duration: object.duration ?? null });
    });
    // Private until the poster is in place, so the first thing PeerTube ever
    // hears of the video already carries the poster vidra cannot size.
    await check('G4b: a video whose poster size vidra cannot read is stored by PeerTube', async () => {
      let video = null;
      try {
        video = await vidra.publish(handle, `Vidra unsized poster ${nonce}`, { privacy: 'private' });
      } catch (error) { throw new Blocked(`vidra did not publish the private upload: ${error.message}`); }
      const own = await vidra.api(`/api/v1/videos/${video.id}/thumbnail`, { binary: true });
      blockedUnless(own.status === 200 && own.bytes[0] === 0xff && own.bytes[1] === 0xd8, `vidra served no JPEG poster for it (HTTP ${own.status})`);
      // A VALID JPEG that vidra cannot size. vidra reads the first 256 KiB of a
      // poster to find its frame header (video_object.go maxPosterHeaderBytes);
      // five maximum-length comment segments, placed after the leading APPn
      // segments, put that header 320 KiB in.
      let at = 2;
      while (own.bytes[at] === 0xff && own.bytes[at + 1] >= 0xe0 && own.bytes[at + 1] <= 0xef) at += 2 + own.bytes.readUInt16BE(at + 2);
      const comment = Buffer.concat([Buffer.from([0xff, 0xfe, 0xff, 0xff]), Buffer.alloc(65533, 0x20)]);
      const poster = Buffer.concat([own.bytes.subarray(0, at), ...Array(5).fill(comment), own.bytes.subarray(at)]);
      const set = await vidra.setPoster(video.id, poster, 'poster.jpg');
      blockedUnless(set.status === 201, `vidra refused the poster: HTTP ${set.status} ${(set.text ?? '').slice(0, 200)}`);
      const since = new Date().toISOString();
      const flipped = await vidra.patch(video.id, { privacy: 'public' });
      blockedUnless(flipped.status === 200, `vidra refused to make the video public: HTTP ${flipped.status} ${(flipped.text ?? '').slice(0, 200)}`);
      const object = await vidraObject(video,
        o => Boolean(o.icon?.[0]?.url) && o.icon[0].width === undefined && o.icon[0].height === undefined,
        o => `its icon is ${JSON.stringify(o.icon ?? null)}`);
      return storedByPeerTube(video, since, { icon: object.icon[0], poster_bytes: poster.length });
    });
  });

  // ------------------------------------------------------------------- G6
  // PeerTube requires `duration` (videos.js "duration format"); vidra leaves it
  // out when its probe read none. The fixture is a WebM written to a pipe,
  // which states no duration — the shape a browser's MediaRecorder produces.
  await scenario('G6', 'a vidra video of unknown duration: does PeerTube store it', async check => {
    blockedUnless(state.s1, 'S1 did not establish the instance follow, so PeerTube has no reason to receive anything');
    await check('G6: an upload whose container states no duration is stored by PeerTube', async () => {
      const since = new Date().toISOString();
      let video = null;
      try {
        video = await vidra.publish(handle, `Vidra no duration ${nonce}`, { source: { bytes: noDurationFixture, filename: 'interop-noduration.webm' }, needHls: false });
      } catch (error) { throw new Blocked(`vidra did not publish the upload with no duration: ${error.message}`); }
      const object = await vidraObject(video, o => o.duration === undefined, o => `it carries duration ${JSON.stringify(o.duration)}`);
      return storedByPeerTube(video, since, { duration: object.duration ?? null, icon: object.icon ?? null });
    });
  });

  // ------------------------------------------------------------------- G7
  // PeerTube 8.3.2 builds a playlist row from vidra's HLS link, which has an
  // empty `tag`: no files and no segment hashes. S2 shows the playlist is
  // fetchable; this shows whether PeerTube's own player plays it.
  await scenario('G7', 'PeerTube\'s watch page plays the vidra video in a real browser', async (check, observe) => {
    blockedUnless(state.s2Video, 'S2 put no vidra video on PeerTube, so there is nothing to play');
    let report = null;
    await check('G7: the player plays it: readyState, currentTime advancing, decoded frames', async () => {
      report = await watchOnPeerTube(PT, state.s2Video.id, { play: true });
      const played = report.playback;
      assert.ok(played, `the watch page never created a <video> element: ${JSON.stringify(report)}`);
      assert.equal(played.media_error, null, `the <video> element reported an error: ${JSON.stringify(report)}`);
      assert.ok(played.ready_state_max >= 3, `readyState never reached 3 (HAVE_FUTURE_DATA): ${JSON.stringify(report)}`);
      assert.ok(played.current_time_to - played.current_time_from >= 1, `currentTime did not advance by a second: ${JSON.stringify(report)}`);
      assert.ok(played.decoded_frames > 0 && !played.video_size.startsWith('0x'), `no frame was decoded: ${JSON.stringify(report)}`);
      return { browser: report.browser, url: report.url, ...played, requests_answered_by_vidra: report.requests_answered_by_vidra };
    });
    await observe('G7: is P2P cleanly off for a playlist with no files and no segment hashes', async () =>
      (report?.p2p
        ? { ...report.p2p, failed_requests: report.failed_requests, page_errors: report.page_errors,
          tracker_urls_peertube_lists_for_it: (await pt.video(state.s2Video.id)).json?.trackerUrls ?? null }
        : { error: 'nothing was played' }));
    // G5: the padded title, as a person sees it on PeerTube.
    await observe('G5: how PeerTube\'s watch page shows the 2-character title', async () => {
      if (!state.shortVideo) return { error: 'the 2-character title never appeared on PeerTube' };
      return (await watchOnPeerTube(PT, state.shortVideo.id, { play: false })).title;
    });
  });

  // ------------------------------------------------------------------- S8
  await scenario('S8', 'negatives: vidra refuses what it must', async check => {
    const privateKey = labPsql('pt-db', `select "privateKey" from actor where "preferredUsername" = 'peertube' and "serverId" is null`);
    blockedUnless(privateKey.includes('PRIVATE KEY'), 'could not read the pt instance actor key from the lab PeerTube database');
    const ptActor = `https://${PT}/accounts/peertube`;
    const keyId = `${ptActor}#main-key`;
    // An activity type vidra accepts and ignores: a valid one changes nothing.
    const activity = (tag, extra = {}) => Buffer.from(JSON.stringify({
      '@context': 'https://www.w3.org/ns/activitystreams',
      id: `https://${PT}/lab/${nonce}/${tag}`, type: 'Listen', actor: ptActor, object: instanceActor, ...extra,
    }));
    // THE BASELINE. Every negative below is only meaningful if the same request
    // WITHOUT the defect is accepted; otherwise a 401 proves the driver cannot
    // sign, not that vidra caught anything.
    const baseline = await check('baseline: a correctly signed activity from the pt actor is accepted (202)', async () => {
      const result = await signedPost('/inbox', activity('baseline'), { keyId, privateKey });
      assert.equal(result.status, 202, `body: ${result.text.slice(0, 300)}`);
      return { status: result.status };
    });
    const refused = async (name, send, wanted) => check(name, async () => {
      blockedUnless(baseline, 'the baseline signed request was not accepted, so this negative would prove nothing');
      const result = await send();
      assert.ok(wanted.includes(result.status), `expected HTTP ${wanted.join('/')}, got ${result.status}. Body: ${result.text.slice(0, 300)}`);
      return { status: result.status };
    });
    await refused('tampered body (signed digest no longer matches) is refused',
      () => signedPost('/inbox', activity('tamper'), { keyId, privateKey, sentBody: activity('tamper', { object: channelActor }) }), [400, 401]);
    await refused('stale Date (one hour old, otherwise valid) is refused',
      () => signedPost('/inbox', activity('stale'), { keyId, privateKey, date: new Date(Date.now() - 3600 * 1000) }), [400, 401]);
    await refused('unsigned POST is refused',
      () => signedPost('/inbox', activity('unsigned'), { keyId, privateKey, omitSignature: true }), [400, 401]);
    await refused('oversized body (1.5 MiB, correctly signed) is refused',
      () => signedPost('/inbox', activity('big', { summary: 'x'.repeat(1536 * 1024) }), { keyId, privateKey }), [400, 401, 413]);
    // The key id names an actor on redir.interop.test, which 302s to the real
    // pt actor. Signed with pt's real key: if vidra followed the hop and took
    // the key it found, the signature would VERIFY and a host would have
    // borrowed another host's identity.
    await refused('an actor URL that redirects to another host is refused',
      () => {
        const redirActor = `https://${REDIR}/accounts/peertube`;
        const body = Buffer.from(JSON.stringify({
          '@context': 'https://www.w3.org/ns/activitystreams',
          id: `https://${REDIR}/lab/${nonce}/redirect`, type: 'Listen', actor: redirActor, object: instanceActor,
        }));
        return signedPost('/inbox', body, { keyId: `${redirActor}#main-key`, privateKey });
      }, [400, 401]);
    // A blocked domain is answered 202 on the wire BY DESIGN (a distinguishable
    // refusal is a probe target), so the assertion is behavioural: a real
    // PeerTube on a blocked domain asks to follow and must not become a follower.
    await check('a follow from a blocked domain (ctl) is not accepted', async () => {
      expectStatus(
        await vidra.api('/api/v1/admin/instances/blocked', { method: 'POST', body: { domain: CTL, reason: 'interop lab S8' } }), [200, 201, 204], 'vidra blocks ctl',
      );
      await ctl.followInstance(VIDRA);
      const held = await holdsFor('ctl is not an accepted instance follower', { windowMs: 30000 }, async () => {
        const stored = vidraPsql(`select state from instance_followers where remote_actor_url like ${sqlText(`https://${CTL}/%`)}`);
        const row = (await ctl.following()).find(f => f.following?.host === VIDRA);
        return { changed: stored === 'accepted' || row?.state === 'accepted', vidra_row: stored || null, ctl_state: row?.state ?? null };
      });
      assert.ok(held.held, `a blocked domain became a follower: ${JSON.stringify(held)}`);
      return held;
    });
    // The lab runs with the SSRF relax ON, so the only SSRF claim it may make
    // is that the shipped production template still has it OFF.
    await check('env/production.env.example still ships HTTP_IMPORT_ALLOW_PRIVATE_URLS=false', async () => {
      const template = readFileSync(new URL('../../env/production.env.example', import.meta.url), 'utf8');
      const lines = template.split('\n').filter(l => /^HTTP_IMPORT_ALLOW_PRIVATE_URLS=/.test(l));
      assert.deepEqual(lines, ['HTTP_IMPORT_ALLOW_PRIVATE_URLS=false']);
      return { line: lines[0] };
    });
  });
};

try {
  await (mode === 'control' ? runControl() : runVidra());
} catch (error) {
  // Outside a scenario: the driver could not even set up. Exit 2, which run.sh
  // reports as a HARNESS failure, never as a scenario verdict.
  console.error(`[pt-interop ${mode}] DRIVER FAILURE: ${error.stack ?? error.message}`);
  process.exit(2);
}
finish();
