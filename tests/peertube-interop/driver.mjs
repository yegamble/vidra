#!/usr/bin/env node
// tests/peertube-interop/driver.mjs — the scenarios of the PeerTube interop lab.
//
//   node driver.mjs control   PeerTube <-> PeerTube: a follow plus a federated video
//   node driver.mjs vidra     S1-S8, vidra <-> PeerTube v8.3.2
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
// whole table: S7 is EXPECTED to fail while plan gaps G8/G10 are open, and
// stopping at the first red would hide every later result. Each scenario
// records pass / fail / blocked plus the UTC window it ran in, so the matching
// PeerTube and vidra log lines can be cut out of out/logs/ afterwards.
// `blocked` is not `fail`: it means a step this scenario DEPENDS on never
// happened, so the scenario measured nothing.
//
// WHAT THIS DELIBERATELY DOES NOT PROVE — do not over-read a green run:
//   * NOTHING ABOUT SSRF. Both sides run with their private-address guard off.
//   * NOTHING ABOUT THE REAL EDGE. No Cloudflare, no WAF, no public DNS, no
//     ACME; the shipped Caddyfile's routing is real, its TLS is not.
//   * NO BROWSER AND NO DECODER. "PeerTube can play it" is asserted as
//     playlist text plus segment bytes fetched from the URLs PeerTube stored.
//
// Inputs (environment, all set by run.sh):
//   EDGE_PORT, LAB_CA_FILE, LAB_OUT, LAB_FIXTURE, LAB_COMPOSE_FILE,
//   PT_ROOT_PASSWORD, and for `vidra`: OWNER_CLAIM_TOKEN, LAB_VIDRA_PROJECT
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, createSign, randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import https from 'node:https';

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
  execFileSync('docker', args, { input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], maxBuffer: 64 * 1024 * 1024 });
const labPsql = (service, sql) =>
  docker(['compose', '-f', labCompose, 'exec', '-T', service, 'psql', '-U', 'peertube', '-d', 'peertube', '-At', '-c', sql]).trim();

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
    upload: async name => {
      const form = multipart({
        channelId: channel.id, name, privacy: 1, waitTranscoding: 'false',
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
  try {
    await body(check);
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
};

// ====================================================================== vidra
const runVidra = async () => {
  throw new Error('S1-S8 are not implemented yet');
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
