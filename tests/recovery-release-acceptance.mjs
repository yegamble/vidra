#!/usr/bin/env node
// Browser half of the v0.6.4 recovery drill (recovery_release_acceptance.py is
// the host half). Real Chromium against the released stack; SQL is SELECT-only
// readback, never a seed or repair. Credentials and TOTP material stay in the
// 0600 private files named below and are never written to result.json.
//
//   node recovery-release-acceptance.mjs STAGE ACTION
//
// ACTION (run in this order on the source, then `verify-restore` on the
// replacement host):
//   upload-kill         browser upload of a long fixture; SIGKILL the api (the
//                       inline worker) while its transcode job is running
//   recovered-playback  wait for the orphaned lease to lapse and the job to
//                       finish on its own, then decode the result in Chromium
//   search-catchup      stop search, edit the drill video's title, restart
//                       search, prove the outbox retry delivered it
//   mfa-enroll          sealed-secret fixture: TOTP on the owner, proven by a
//                       real two-factor browser sign-in BEFORE the backup
//   rpo-marker          one write AFTER the backup, which a restore must lose
//   verify-restore      replacement host: password+TOTP sign-in (wrong code
//                       refused), rpo marker absent, decode old media from the
//                       bucket, find the drill video through real search, then
//                       upload and decode a NEW video
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHmac, randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';

const ACTIONS = ['upload-kill', 'recovered-playback', 'search-catchup', 'mfa-enroll', 'rpo-marker', 'verify-restore'];
const [stageArg, action] = process.argv.slice(2);
assert.ok(stageArg && ACTIONS.includes(action), `usage: recovery-release-acceptance.mjs STAGE ${ACTIONS.join('|')}`);
assert.equal(process.env.COMPOSE_PROJECT_NAME, 'vidra-release-acceptance');
const baseline = '/root/vidra-v064-runtime';
const drill = resolve(stageArg);
const out = join(drill, action);
assert.ok(!existsSync(out), 'use a new stage per attempt; failed evidence is retained');
mkdirSync(join(out, 'private'), { recursive: true, mode: 0o700 });
const origin = 'https://secure.video.test';
const result = { status: 'UNVERIFIED', action, checks: {}, node: process.version, commands: [], started_at: new Date().toISOString() };
const save = () => writeFileSync(join(out, 'result.json'), JSON.stringify(result, null, 2) + '\n', { mode: 0o600 });
const shared = name => join(drill, 'private', name);
mkdirSync(join(drill, 'private'), { recursive: true, mode: 0o700 });
const readShared = name => JSON.parse(readFileSync(shared(name), 'utf8'));
const writeShared = (name, value) => writeFileSync(shared(name), JSON.stringify(value, null, 2), { mode: 0o600 });
const host = (args, timeout = 300000) => {
  const entry = { argv: args, started_at: new Date().toISOString() }; result.commands.push(entry);
  try {
    const output = execFileSync(args[0], args.slice(1), { cwd: '/opt/vidra', encoding: 'utf8', timeout,
      maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
    entry.exit_code = 0; return output.trim();
  } catch (error) { entry.exit_code = error.status ?? 'TIMEOUT'; throw error; }
};
const compose = (...args) => host(['bash', 'deploy/compose.sh', ...args]);
const sql = query => {
  assert.match(query, /^SELECT /, 'acceptance evidence must not seed or repair database state');
  return compose('exec', '-T', 'postgres', 'psql', '-U', 'vidra', '-d', 'vidra', '-At', '-v', 'ON_ERROR_STOP=1', '-c', query);
};
const uuid = value => { assert.match(value, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/); return value; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
let phase = 'preconditions';
const step = name => { phase = name; console.log(`[recovery-browser] ${action}: ${name}`); save(); };

// RFC 6238, the parameters /auth/mfa/totp documents: SHA1, 6 digits, 30 s.
export const base32 = text => {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits = '';
  for (const c of text.replace(/=+$/, '').toUpperCase()) {
    const i = alphabet.indexOf(c); assert.ok(i >= 0, 'invalid base32 secret'); bits += i.toString(2).padStart(5, '0');
  }
  const bytes = []; for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
};
export const totp = (secret, now = Date.now()) => {
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(now / 30000)));
  const mac = createHmac('sha1', base32(secret)).update(counter).digest(); const offset = mac[19] & 15;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1000000).padStart(6, '0');
};
// The server records the last accepted step (migration 0134), so a code is
// single-use: wait for a step no earlier sign-in has consumed.
let lastStep = 0;
const freshCode = async secret => {
  while (Math.floor(Date.now() / 30000) <= lastStep || Date.now() % 30000 > 25000) await sleep(1000);
  lastStep = Math.floor(Date.now() / 30000); return totp(secret);
};

let browser;
try {
  const { chromium, expect } = createRequire(join(baseline, 'browser/package.json'))('@playwright/test');
  const poll = async (check, timeout = 180000) => expect(check).toPass({ timeout, intervals: [250, 500, 1000, 2000] });
  const owner = JSON.parse(readFileSync(join(baseline, 'private/owner.json'), 'utf8'));
  result.browser_args = ['--host-resolver-rules=MAP secure.video.test 127.0.0.1', '--no-proxy-server', '--autoplay-policy=no-user-gesture-required'];
  browser = await chromium.launch({ args: result.browser_args });
  result.browser = browser.version();
  const newPage = async () => {
    const context = await browser.newContext({ baseURL: origin, ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1000 } });
    const page = await context.newPage(); page.setDefaultTimeout(60000); return page;
  };
  const api = (page, path, token, method = 'GET', body) => page.evaluate(async ({ path, token, method, body }) => {
    const response = await fetch(path, { method, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined });
    const text = await response.text(); let json = null; try { json = JSON.parse(text); } catch { /* not JSON */ }
    return { status: response.status, body: json, retryAfter: response.headers.get('retry-after') };
  }, { path, token, method, body });

  // Real sign-in form. Request limits stay ON: a 429 is waited out, not disabled.
  const signIn = async (page, { expectMfa = false, wrongCodeFirst = false } = {}) => {
    for (let attempt = 0; ; attempt++) {
      await page.goto('/login');
      await page.getByLabel('Email or username', { exact: true }).fill(owner.email);
      await page.getByLabel('Password', { exact: true }).fill(owner.password);
      const pending = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/login') && r.request().method() === 'POST');
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      const response = await pending;
      if (response.status() === 429 && attempt < 5) { await sleep((Number(response.headers()['retry-after']) || 30) * 1000 + 1000); continue; }
      assert.equal(response.status(), 200);
      const body = await response.json();
      if (!expectMfa) { assert.ok(body.token && !body.mfa_required, 'expected a direct session'); return body; }
      assert.equal(body.mfa_required, true, 'restored account must still demand its second factor');
      assert.ok(!body.token, 'an MFA challenge must not carry session tokens');
      const secret = readShared('mfa.json').secret;
      const submit = async code => {
        await page.getByRole('group', { name: 'Authentication code' }).getByRole('textbox').first().click();
        await page.keyboard.type(code);
        const challenge = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/mfa/challenge'));
        await page.getByRole('button', { name: 'Verify code', exact: true }).click();
        return challenge;
      };
      if (wrongCodeFirst) {
        // An undecryptable secret answers exactly like a wrong code (A37-1), so
        // a refusal proves nothing alone: the proof is refusal of a wrong code
        // AND acceptance of the right one below, on the same restored secret.
        const probe = await page.evaluate(async ({ email, password }) => {
          const login = await fetch('/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ identifier: email, password }) });
          const body = await login.json();
          return { login: login.status, mfa_token: body.mfa_token ?? null };
        }, { email: owner.email, password: owner.password });
        assert.equal(probe.login, 200); assert.ok(probe.mfa_token);
        const good = totp(secret); const wrong = String((Number(good) + 500000) % 1000000).padStart(6, '0');
        const refused = await api(page, '/api/v1/auth/mfa/challenge', null, 'POST', { mfa_token: probe.mfa_token, code: wrong });
        result.wrong_code_status = refused.status; assert.equal(refused.status, 401, 'a wrong TOTP code was not refused');
      }
      const accepted = await submit(await freshCode(secret));
      assert.equal(accepted.status(), 200, 'the restored TOTP secret did not verify');
      const auth = await accepted.json(); assert.ok(auth.token); return auth;
    }
  };

  const uploadAndPublish = async (page, auth, file, title) => {
    const nonce = randomBytes(4).toString('hex'); const handle = `recovery${nonce}`;
    await page.getByRole('link', { name: 'Studio', exact: true }).click();
    await page.getByRole('link', { name: 'Channel', exact: true }).click();
    const another = page.getByRole('button', { name: 'Create another channel', exact: true });
    await expect(another.or(page.getByLabel('Channel handle'))).toBeVisible();
    if (await another.isVisible()) await another.click();
    await page.getByLabel('Channel handle').fill(handle);
    await page.getByLabel('Channel display name').fill(`Recovery ${nonce}`);
    const pendingChannel = page.waitForResponse(r => r.url().endsWith('/api/v1/channels') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Create channel', exact: true }).click();
    assert.equal((await pendingChannel).status(), 201);
    await expect(page.getByRole('dialog', { name: 'Create a channel', exact: true })).toHaveCount(0);
    const switcher = page.getByRole('button', { name: /^Switch channel/ });
    if (await switcher.count()) { await switcher.click(); await page.getByRole('menuitem').filter({ hasText: `@${handle}` }).click(); }
    await page.getByRole('link', { name: 'Content', exact: true }).click();
    const pendingDraft = page.waitForResponse(r => /\/channels\/[^/]+\/videos$/.test(r.url()) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Upload video', exact: true }).click();
    await page.getByLabel('Video file', { exact: true }).setInputFiles(file);
    const draft = await (await pendingDraft).json(); const id = uuid(draft.id);
    await page.getByLabel('Video title').fill(title);
    await page.getByLabel('Privacy', { exact: true }).selectOption('public');
    const pendingComplete = page.waitForResponse(r => /\/uploads\/[^/]+\/complete$/.test(r.url()) && r.request().method() === 'POST', { timeout: 900000 });
    await page.getByRole('button', { name: 'Publish', exact: true }).click();
    assert.equal((await pendingComplete).status(), 202);
    return id;
  };
  const job = id => { const row = sql(`SELECT row_to_json(j) FROM (SELECT id,state,attempts,next_attempt_at,last_error IS NOT NULL AS has_error,created_at,updated_at FROM transcode_jobs WHERE video_id='${id}' ORDER BY created_at DESC LIMIT 1) j`); return row ? JSON.parse(row) : null; };

  const playback = async (id, label) => {
    const page = await newPage();
    await page.goto(`/videos/${id}`);
    const video = page.locator('#main-content').getByTestId('video-player').first().locator('video');
    await expect(video).toBeVisible();
    await poll(async () => assert.ok(await video.evaluate(v => v.readyState >= 2 && v.duration > 5)));
    await video.evaluate(v => { v.pause(); v.currentTime = 0; v.muted = false; v.volume = 1; });
    const sample = () => video.evaluate(v => ({ time: v.currentTime, frames: v.getVideoPlaybackQuality().totalVideoFrames,
      audio_bytes: v.webkitAudioDecodedByteCount ?? 0, width: v.videoWidth, height: v.videoHeight,
      src_blob: v.currentSrc.startsWith('blob:'), paused: v.paused, muted: v.muted, error: v.error?.message ?? null }));
    const start = await sample(); let end;
    await video.evaluate(v => Promise.race([v.play(), new Promise((_, reject) => setTimeout(() => reject(new Error('play timeout')), 15000))]));
    await poll(async () => {
      end = await sample();
      assert.ok(end.time - start.time >= 2 && end.frames > start.frames && end.audio_bytes > start.audio_bytes);
      assert.equal(end.error, null); assert.equal(end.muted, false); assert.ok(end.width > 0 && end.height > 0);
    }, 60000);
    await page.screenshot({ path: join(out, `playback-${label}.png`) });
    await page.context().close();
    return { id, start, end };
  };

  const searchService = () => {
    const container = compose('ps', '-q', 'search');
    return Number(host(['python3', '-c', `
import json,subprocess,sys,urllib.request
c=json.loads(subprocess.check_output(['docker','inspect',sys.argv[1]]))[0]
ip=next(v['IPAddress'] for v in c['NetworkSettings']['Networks'].values() if v['IPAddress'])
lines=urllib.request.urlopen('http://'+ip+':8080/metrics',timeout=15).read().decode().splitlines()
print(sum(float(l.rsplit(' ',1)[1]) for l in lines if l.startswith('vidra_search_http_requests_total{') and 'route="/internal/v1/search"' in l and 'status_class="2xx"' in l))
`, container]));
  };
  // The UI query must be answered by vidra-search itself: only a real service
  // round trip raises its 2xx counter; the local SQL fallback cannot.
  const uiSearch = async (page, query, id) => {
    const before = searchService();
    for (let attempt = 0; ; attempt++) {
      await page.goto('/');
      const pending = page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname === '/api/v1/videos/search' && u.searchParams.get('q') === query; });
      const box = page.getByRole('combobox', { name: /Search/ });
      await box.fill(query); await box.press('Enter');
      const response = await pending;
      if (response.status() === 429 && attempt < 5) { await sleep((Number(response.headers()['retry-after']) || 30) * 1000 + 1000); continue; }
      assert.equal(response.status(), 200);
      const body = await response.json();
      assert.ok(JSON.stringify(body).includes(id), 'search response lacks the drill video');
      break;
    }
    const after = searchService(); assert.ok(after > before, 'search was not served by vidra-search');
    await page.getByRole('link', { name: query }).first().click();
    await expect(page.getByRole('heading', { name: query, exact: true })).toBeVisible();
    return { query, service_requests_before: before, service_requests_after: after };
  };

  if (action === 'upload-kill') {
    step('generate-long-fixture');
    // A 180 s 720p clip keeps the transcode running long enough to kill it
    // mid-flight. Generated by the released core image's own ffmpeg.
    const scratch = join(out, 'fixture'); mkdirSync(scratch, { mode: 0o777 }); host(['chmod', '0777', scratch]);
    const image = JSON.parse(readFileSync(join(baseline, 'candidate.json'), 'utf8')).images['vidra-core'].reference;
    host(['docker', 'run', '--rm', '--entrypoint', 'ffmpeg', '-v', `${scratch}:/out`, image, '-hide_banner', '-loglevel', 'error',
      '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=180', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=180',
      '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '/out/recovery-drill.mp4'], 900000);
    result.fixture_sha256 = host(['sha256sum', join(scratch, 'recovery-drill.mp4')]).split(' ')[0];
    step('browser-upload');
    const page = await newPage();
    const auth = await signIn(page);
    await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible();
    const title = `Recoverydrill${randomBytes(4).toString('hex')}`;
    const id = await uploadAndPublish(page, auth, join(scratch, 'recovery-drill.mp4'), title);
    writeShared('drill.json', { video_id: id, title });
    result.video_id = id; result.title = title;
    step('kill-api-while-transcoding');
    result.job_observations = [];
    await poll(() => { const j = job(id); result.job_observations.push(j); assert.equal(j?.state, 'running'); }, 900000);
    const apiContainer = compose('ps', '-q', 'api');
    result.killed_container = apiContainer; result.killed_at = new Date().toISOString();
    host(['docker', 'kill', '--signal', 'KILL', apiContainer]);
    await sleep(5000);
    const killedState = JSON.parse(host(['docker', 'inspect', '--format', '{{json .State}}', apiContainer]));
    result.state_after_kill = { status: killedState.Status, exit_code: killedState.ExitCode, oom: killedState.OOMKilled };
    compose('up', '-d', 'api');
    await poll(() => assert.equal(host(['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', 'http://127.0.0.1:8080/readyz']), '200'), 300000);
    result.api_ready_again_at = new Date().toISOString();
    result.job_after_restart = job(id);
    assert.notEqual(result.job_after_restart?.state, 'done', 'job finished before the kill; the recovery was not exercised');
    result.checks[phase] = 'PASS';
  } else if (action === 'recovered-playback') {
    const { video_id: id } = readShared('drill.json');
    step('orphaned-lease-recovers-without-intervention');
    // The claim pushed next_attempt_at 30 minutes out and nobody renews it
    // now, so the sweep may take it back only after that lease lapses. Poll
    // slowly and keep only transitions: this is a wait, not a load test.
    result.job_transitions = [];
    const began = Date.now(); const deadline = began + 45 * 60000; let last = '';
    for (;;) {
      const j = job(id); const key = `${j?.state}|${j?.attempts}|${j?.next_attempt_at}`;
      if (key !== last) { result.job_transitions.push({ at: new Date().toISOString(), ...j }); last = key; save(); }
      if (j?.state === 'done') break;
      assert.ok(j?.state !== 'failed', 'the orphaned job failed instead of recovering');
      assert.ok(Date.now() < deadline, 'the orphaned job did not recover within 45 minutes');
      await sleep(20000);
    }
    result.recovery_wait_seconds = Math.round((Date.now() - began) / 1000);
    result.final_job = job(id);
    result.job_runs = JSON.parse(sql(`SELECT COALESCE(json_agg(r ORDER BY r.created_at),'[]') FROM (SELECT type,state,attempt,worker_id,created_at,claimed_at,started_at,finished_at,lease_expires_at,error_class FROM job_runs WHERE resource_id::text='${id}') r`));
    result.checks[phase] = 'PASS';
    step('recovered-video-decodes');
    result.playback = await playback(id, 'recovered');
    result.checks[phase] = 'PASS';
  } else if (action === 'search-catchup') {
    const drillInfo = readShared('drill.json');
    const page = await newPage(); const auth = await signIn(page);
    step('write-while-search-is-down');
    compose('stop', 'search'); result.search_stopped_at = new Date().toISOString();
    const title = `Recoverycatchup${randomBytes(4).toString('hex')}`;
    const edit = await api(page, `/api/v1/videos/${drillInfo.video_id}`, auth.token, 'PATCH', { title });
    assert.equal(edit.status, 200); assert.equal(edit.body.title, title);
    await sleep(15000);
    result.outbox_while_down = sql(`SELECT COALESCE(json_agg(o ORDER BY o.id),'[]') FROM (SELECT id,event_type,state,attempts FROM search_outbox WHERE payload::text LIKE '%${drillInfo.video_id}%' ORDER BY id DESC LIMIT 3) o`);
    const fallback = await api(page, `/api/v1/videos/search?q=${encodeURIComponent(title)}`);
    result.search_while_down = { status: fallback.status, found: JSON.stringify(fallback.body ?? '').includes(drillInfo.video_id) };
    assert.equal(fallback.status, 200, 'search outage broke the public search endpoint');
    result.checks[phase] = 'PASS';
    step('restart-search-and-catch-up');
    compose('start', 'search'); result.search_started_at = new Date().toISOString();
    await poll(() => {
      const doc = sql(`SELECT title FROM search.documents WHERE video_id='${drillInfo.video_id}'`);
      assert.equal(doc, title, 'search index has not caught up with the write made during the outage');
    }, 900000);
    result.caught_up_at = new Date().toISOString();
    result.ui_search = await uiSearch(page, title, drillInfo.video_id);
    writeShared('drill.json', { ...drillInfo, title });
    result.checks[phase] = 'PASS';
  } else if (action === 'mfa-enroll') {
    const page = await newPage();
    step('enroll-totp');
    const auth = await signIn(page);
    const begin = await api(page, '/api/v1/auth/mfa/totp', auth.token, 'POST');
    assert.equal(begin.status, 200); assert.ok(begin.body.secret);
    writeShared('mfa.json', { secret: begin.body.secret });
    const verify = await api(page, '/api/v1/auth/mfa/totp/verify', auth.token, 'POST', { code: await freshCode(begin.body.secret) });
    assert.equal(verify.status, 200);
    writeShared('mfa.json', { secret: begin.body.secret, recovery: verify.body });
    const status = await api(page, '/api/v1/auth/mfa', auth.token);
    assert.equal(status.status, 200); assert.equal(status.body.enabled, true);
    result.mfa_status = { enabled: status.body.enabled, recovery_codes_remaining: status.body.recovery_codes_remaining };
    assert.equal(sql(`SELECT count(*) FROM user_mfa WHERE user_id='${auth.user.id}'`), '1');
    result.checks[phase] = 'PASS';
    step('two-factor-browser-sign-in-before-backup');
    const fresh = await newPage();
    await signIn(fresh, { expectMfa: true });
    await expect(fresh.getByRole('button', { name: 'Open account menu' })).toBeVisible();
    result.checks[phase] = 'PASS';
  } else if (action === 'rpo-marker') {
    const page = await newPage();
    step('write-after-backup');
    const auth = await signIn(page, { expectMfa: true });
    const marker = `RPO marker ${randomBytes(4).toString('hex')}`;
    const edit = await api(page, '/api/v1/auth/me', auth.token, 'PATCH', { display_name: marker });
    assert.equal(edit.status, 200); assert.equal(edit.body.display_name, marker);
    writeShared('rpo.json', { display_name: marker, written_at: new Date().toISOString() });
    result.marker = marker; result.written_at = new Date().toISOString();
    result.checks[phase] = 'PASS';
  } else {
    const drillInfo = readShared('drill.json'); const rpo = readShared('rpo.json');
    const page = await newPage();
    step('restored-account-password-and-sealed-totp');
    const auth = await signIn(page, { expectMfa: true, wrongCodeFirst: true });
    await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible();
    const me = await api(page, '/api/v1/auth/me', auth.token);
    assert.equal(me.status, 200); assert.equal(me.body.username, owner.username); assert.equal(me.body.role, 'admin');
    result.checks[phase] = 'PASS';
    step('write-after-backup-is-lost');
    const displayName = me.body.display_name;
    assert.notEqual(displayName, rpo.display_name, 'the post-backup write survived; the restore is not from the backup data point');
    result.rpo = { marker_written_at: rpo.written_at, marker_present: false };
    result.checks[phase] = 'PASS';
    step('old-media-decodes-from-the-bucket');
    const legacy = JSON.parse(readFileSync(join(baseline, 'browser-result.json'), 'utf8')).video_id;
    result.playback_legacy = await playback(uuid(legacy), 'legacy');
    result.playback_drill = await playback(drillInfo.video_id, 'drill');
    result.checks[phase] = 'PASS';
    step('restored-search-index-serves-ui');
    result.ui_search = await uiSearch(page, drillInfo.title, drillInfo.video_id);
    result.checks[phase] = 'PASS';
    step('new-upload-transcodes-and-decodes');
    const fresh = await newPage(); const freshAuth = await signIn(fresh, { expectMfa: true });
    const title = `Postrestore${randomBytes(4).toString('hex')}`;
    const id = await uploadAndPublish(fresh, freshAuth, join(baseline, 'fixture.mp4'), title);
    await poll(() => assert.equal(job(id)?.state, 'done'), 2400000);
    result.new_video = { id, title, job: job(id) };
    result.playback_new = await playback(id, 'new');
    result.checks[phase] = 'PASS';
  }
  result.status = 'PASS';
} catch (error) {
  result.status = 'FAIL'; result.failed_phase = phase; result.error = String(error?.stack ?? error).slice(0, 4000);
  process.exitCode = 1;
} finally {
  result.finished_at = new Date().toISOString(); save();
  await browser?.close();
}
