#!/usr/bin/env node
// Bounded A04/A06/A07/A09 continuation. Browser mutations, read-only SQL proof,
// real services, and fresh artifacts only; no imported historical PASS or mocks.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { checkCookieSession, checkIdentity } from './owner-auth-smoke.mjs';

const stage = resolve(process.argv[2] ?? '');
assert.ok(process.argv[2], 'usage: release-acceptance.mjs PREPARED_HOST_STAGE');
assert.equal(process.env.COMPOSE_PROJECT_NAME, 'vidra-release-acceptance');
assert.ok(Number(process.versions.node.split('.')[0]) >= 24);
const origin = 'https://secure.video.test';
const result = { status: 'UNVERIFIED', checks: {}, node: process.version, media_requests: [], commands: [] };
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const checkpoint = () => writeFileSync(join(stage, 'browser-result.json'), JSON.stringify(result, null, 2) + '\n', { mode: 0o600 });
const host = args => {
  const entry = { argv: args, started_at: new Date().toISOString() }; result.commands.push(entry);
  try { const output = execFileSync(args[0], args.slice(1), { cwd: '/opt/vidra', encoding: 'utf8', timeout: 120000,
    maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] }); entry.exit_code = 0; return output.trim(); }
  catch (error) { entry.exit_code = error.status ?? 'TIMEOUT'; throw error; }
};
const compose = (...args) => host(['bash', 'deploy/compose.sh', ...args]);
const sql = query => {
  assert.match(query, /^SELECT /, 'acceptance evidence must not seed or repair database state');
  return compose('exec', '-T', 'postgres', 'psql', '-U', 'vidra', '-d', 'vidra', '-At', '-v', 'ON_ERROR_STOP=1', '-c', query);
};
const uuid = value => { assert.match(value, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/); return value; };
let browser, phase = 'preconditions';
const step = name => { phase = name; console.log(`[release-browser] ${name}`); checkpoint(); };
try {
  const { chromium, expect } = createRequire(join(stage, 'browser/package.json'))('@playwright/test');
  const poll = async (check, timeout = 180000) => expect(check).toPass({ timeout, intervals: [250, 500, 1000, 2000] });
  assert.equal(sql('SELECT count(*) FROM users'), '0', 'requires an unclaimed fresh installation');
  const logs = compose('logs', '--no-color', 'api');
  const tokens = [...logs.matchAll(/403 owner_claim_required until claimed\): ([A-Za-z0-9_-]+)/g)];
  assert.ok(tokens.length, 'missing boot claim token');
  const token = tokens.at(-1)[1];
  result.browser_args = ['--host-resolver-rules=MAP secure.video.test 127.0.0.1', '--no-proxy-server', '--autoplay-policy=no-user-gesture-required'];
  browser = await chromium.launch({ args: result.browser_args });
  result.browser = browser.version();
  // curl has already verified Caddy with its test CA. Chromium's independent
  // test context ignores that private CA only; no public TLS claim is made.
  const context = await browser.newContext({ baseURL: origin, ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage(); page.setDefaultTimeout(60000);
  const api = async (path, bearer) => page.evaluate(async ({ path, bearer }) => {
    const response = await fetch(path, { headers: bearer ? { Authorization: `Bearer ${bearer}` } : {} });
    return { status: response.status, body: await response.json() };
  }, { path, bearer });
  const nonce = randomBytes(6).toString('hex');
  const password = randomBytes(24).toString('base64url');
  const owner = { username: `owner${nonce}`, email: `owner${nonce}@example.test`, password };
  writeFileSync(join(stage, 'private/owner.json'), JSON.stringify(owner), { mode: 0o600 });
  step('owner-claim');
  await page.goto('/setup/claim');
  assert.equal((await api('/api/v1/instance')).body.owner_claim_pending, true);
  await page.getByLabel('Setup token').fill(token);
  for (const [label, value] of [['Username', owner.username], ['Email', owner.email], ['Password', owner.password], ['Confirm password', owner.password]]) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  const pendingClaim = page.waitForResponse(r => r.url().endsWith('/api/v1/setup/claim-owner') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create the owner account' }).click();
  const claim = await pendingClaim; assert.equal(claim.status(), 201);
  const claimed = await claim.json(); checkCookieSession(claimed, owner.username, 'admin');
  result.owner_id = uuid(claimed.user.id);
  await expect(page.getByRole('heading', { name: 'Your server is ready' })).toBeVisible();
  await page.getByRole('link', { name: 'Go to the home page' }).click();
  assert.equal((await api('/api/v1/instance')).body.owner_claim_pending, false);
  assert.equal(sql("SELECT count(*) FROM users WHERE role='admin'"), '1');
  await page.screenshot({ path: join(stage, 'owner-claimed.png') });
  result.checks[phase] = 'PASS';

  step('owner-login-and-session');
  await page.getByRole('button', { name: 'Open account menu' }).click();
  await page.getByRole('dialog', { name: 'Account menu' }).getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open account menu' })).toHaveCount(0);
  await page.goto('/login');
  await page.getByLabel('Email or username', { exact: true }).fill(owner.email);
  await page.getByLabel('Password', { exact: true }).fill(owner.password);
  const pendingLogin = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/login') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const login = await pendingLogin; assert.equal(login.status(), 200);
  let auth = await login.json(); checkCookieSession(auth, owner.username, 'admin');
  await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible();
  const reloadSession = async () => {
    const pending = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/refresh'));
    await page.reload(); const response = await pending; assert.equal(response.status(), 200);
    // Refresh revokes the old session, including its access token. Readback
    // must use the newly rotated token, just as the released browser does.
    auth = await response.json(); checkCookieSession(auth, owner.username, 'admin');
    await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible();
  };
  await reloadSession();
  const identity = await api('/api/v1/auth/me', auth.token);
  assert.equal(identity.status, 200); checkIdentity(identity.body, owner.username, 'admin');
  const cookie = (await context.cookies()).find(c => c.name === 'vidra_refresh');
  assert.ok(cookie?.secure && cookie?.httpOnly);
  result.checks[phase] = 'PASS';

  step('browser-channel-upload-publish');
  const handle = `release${nonce}`, title = `Releaseacceptance${nonce}`;
  result.query = title;
  await page.getByRole('link', { name: 'Studio', exact: true }).click();
  await page.getByRole('link', { name: 'Channel', exact: true }).click();
  const another = page.getByRole('button', { name: 'Create another channel', exact: true });
  await expect(another.or(page.getByLabel('Channel handle'))).toBeVisible();
  if (await another.isVisible()) await another.click();
  await page.getByLabel('Channel handle').fill(handle);
  await page.getByLabel('Channel display name').fill(`Release ${nonce}`);
  const pendingChannel = page.waitForResponse(r => r.url().endsWith('/api/v1/channels') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create channel', exact: true }).click();
  const createdChannel = await pendingChannel; assert.equal(createdChannel.status(), 201);
  const channel = await createdChannel.json(); result.channel_id = uuid(channel.id);
  await expect(page.getByRole('dialog', { name: 'Create a channel', exact: true })).toHaveCount(0);
  const switcher = page.getByRole('button', { name: /^Switch channel/ });
  if (await switcher.count()) { await switcher.click(); await page.getByRole('menuitem').filter({ hasText: `@${handle}` }).click(); }
  await expect(page.getByText(`@${handle}`, { exact: true }).first()).toBeVisible();
  assert.equal(sql(`SELECT owner_id FROM channels WHERE id='${channel.id}'`), auth.user.id);
  await page.getByRole('link', { name: 'Content', exact: true }).click();
  const start = Number(sql('SELECT COALESCE(max(id),0) FROM search_outbox'));
  const pendingDraft = page.waitForResponse(r => /\/channels\/[^/]+\/videos$/.test(r.url()) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Upload video', exact: true }).click();
  await page.getByLabel('Video file', { exact: true }).setInputFiles(join(stage, 'fixture.mp4'));
  const draftResponse = await pendingDraft; assert.equal(draftResponse.status(), 201);
  const draft = await draftResponse.json(); const id = uuid(draft.id); result.video_id = id;
  assert.equal(draft.state, 'draft'); assert.equal(draft.privacy, 'private');
  assert.equal(sql(`SELECT channel_id FROM videos WHERE id='${id}'`), channel.id);
  await page.getByLabel('Video title').fill(title);
  await page.getByLabel('Privacy', { exact: true }).selectOption('public');
  const pendingComplete = page.waitForResponse(r => /\/uploads\/[^/]+\/complete$/.test(r.url()) && r.request().method() === 'POST', { timeout: 600000 });
  // v0.6.4 holds completion until Publish persists these details. Waiting for
  // /complete before this click deadlocks the historical A06 driver.
  await page.getByRole('button', { name: 'Publish', exact: true }).click();
  const complete = await pendingComplete; assert.equal(complete.status(), 202);
  result.upload_id = (await complete.json()).upload_id;
  await poll(async () => {
    const detail = await api(`/api/v1/videos/${id}`, auth.token);
    assert.equal(detail.status, 200); assert.equal(detail.body.state, 'published');
    assert.equal(detail.body.title, title); assert.equal(detail.body.privacy, 'public');
  }, 600000);
  const original = await page.evaluate(async id => {
    const r = await fetch(`/api/v1/videos/${id}/original`); const bytes = await r.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return { status: r.status, bytes: bytes.byteLength, type: r.headers.get('content-type'),
      sha256: Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('') };
  }, id);
  assert.equal(original.status, 200); assert.equal(original.type, 'video/mp4');
  assert.equal(original.sha256, hash(readFileSync(join(stage, 'fixture.mp4'))));
  result.original = original; await reloadSession();
  await expect(page.getByText(title, { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: join(stage, 'upload-published.png') });
  result.checks[phase] = 'PASS';

  step('real-transcoding-and-advertised-tree');
  result.jobs = [];
  await poll(() => {
    const row = sql(`SELECT row_to_json(j) FROM (SELECT id,state,attempts,updated_at FROM transcode_jobs WHERE video_id='${id}' ORDER BY created_at DESC LIMIT 1) j`);
    const job = row ? JSON.parse(row) : null; result.jobs.push(job); checkpoint();
    // The released SQL increments attempts on retry/failure, not first claim.
    // A successful first transcode legitimately finishes with attempts=0.
    assert.equal(job?.state, 'done'); assert.ok(Number.isInteger(job.attempts) && job.attempts >= 0);
  }, 2400000);
  const detail = (await api(`/api/v1/videos/${id}`, auth.token)).body;
  assert.equal(detail.packaging_format, 'cmaf'); assert.ok(detail.hls_url && detail.renditions.length);
  result.renditions = detail.renditions; result.assets = [];
  const visited = new Set();
  const visit = async url => {
    if (visited.has(url)) return; visited.add(url); assert.ok(visited.size <= 200);
    assert.equal(new URL(url).origin, origin);
    const asset = await page.evaluate(async url => {
      const response = await fetch(url); const bytes = await response.arrayBuffer();
      return { status: response.status, bytes: bytes.byteLength, type: response.headers.get('content-type'),
        text: new URL(url).pathname.endsWith('.m3u8') ? new TextDecoder().decode(bytes) : null };
    }, url);
    assert.equal(asset.status, 200); assert.ok(asset.bytes > 0);
    result.assets.push({ path: new URL(url).pathname, status: asset.status, bytes: asset.bytes, type: asset.type });
    if (asset.text !== null) {
      assert.ok(asset.text.startsWith('#EXTM3U'));
      const uris = asset.text.split('\n').map(s => s.trim()).filter(s => s && !s.startsWith('#'));
      for (const match of asset.text.matchAll(/URI="([^"]+)"/g)) uris.push(match[1]);
      assert.ok(uris.length);
      for (const uri of uris) await visit(new URL(uri, url).href);
    }
  };
  await visit(new URL(detail.hls_url, origin).href);
  assert.ok(result.assets.some(a => a.path.endsWith('.m4s')));
  assert.ok(result.assets.some(a => a.path.includes('init')));
  result.checks[phase] = 'PASS';

  step('browser-playback-advances');
  const viewer = await browser.newContext({ baseURL: origin, ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1000 } });
  const watch = await viewer.newPage(); watch.setDefaultTimeout(60000);
  watch.on('response', response => {
    const path = new URL(response.url()).pathname;
    if (path.includes(`/videos/${id}/`)) result.media_requests.push({ path, status: response.status() });
  });
  await watch.goto(`/videos/${id}`);
  await expect(watch.getByRole('heading', { name: title, exact: true })).toBeVisible();
  const video = watch.locator('#main-content').getByTestId('video-player').first().locator('video');
  await expect(video).toBeVisible();
  await poll(async () => assert.ok(await video.evaluate(v => v.readyState >= 2 && v.duration >= 11 && v.currentSrc.startsWith('blob:'))));
  await video.evaluate(v => { v.pause(); v.currentTime = 0; v.muted = false; v.volume = 1; });
  const sample = () => video.evaluate(v => ({ time: v.currentTime, frames: v.getVideoPlaybackQuality().totalVideoFrames,
    audio_bytes: v.webkitAudioDecodedByteCount ?? 0, width: v.videoWidth, height: v.videoHeight,
    ready: v.readyState, paused: v.paused, muted: v.muted, error: v.error?.message ?? null }));
  result.playback_start = await sample();
  await video.evaluate(v => Promise.race([v.play(), new Promise((_, reject) => setTimeout(() => reject(new Error('play timeout')), 15000))]));
  await poll(async () => {
    result.playback_end = await sample(); const end = result.playback_end, begin = result.playback_start;
    assert.ok(end.time - begin.time >= 2 && end.frames > begin.frames && end.audio_bytes > begin.audio_bytes);
    assert.equal(end.error, null); assert.equal(end.muted, false); assert.equal(end.paused, false);
    assert.ok(end.width > 0 && end.height > 0 && end.ready >= 2);
  }, 60000);
  await watch.screenshot({ path: join(stage, 'playback-advancing.png') });
  await video.evaluate(v => { v.pause(); v.currentTime = 7; });
  await poll(async () => assert.ok(await video.evaluate(v => Math.abs(v.currentTime - 7) < 0.3 && !v.seeking && v.readyState >= 2)), 15000);
  result.seek = await sample(); result.checks[phase] = 'PASS';

  step('same-upload-through-vidra-search');
  await poll(() => {
    result.upsert_events = JSON.parse(sql(`SELECT COALESCE(json_agg(e),'[]') FROM (SELECT o.id,o.event_id,o.state,o.attempts,(i.event_id IS NOT NULL) AS received FROM search_outbox o LEFT JOIN search.events_inbox i USING(event_id) WHERE o.id>${start} AND o.event_type='video.upsert' AND o.payload::text LIKE '%${id}%' ORDER BY o.id) e`));
    assert.ok(result.upsert_events.some(e => e.state === 'delivered' && e.received));
    const row = sql(`SELECT row_to_json(d) FROM (SELECT video_id,title,eligible FROM search.documents WHERE video_id='${id}') d`);
    result.document = row ? JSON.parse(row) : null; assert.equal(result.document?.title, title); assert.equal(result.document?.eligible, true);
  });
  const searchContainer = compose('ps', '-q', 'search');
  result.internal_search = JSON.parse(host(['python3', '-c', `
import hashlib,hmac,json,subprocess,sys,time,urllib.parse,urllib.request
c=json.loads(subprocess.check_output(['docker','inspect',sys.argv[1]]))[0]
env=dict(v.split('=',1) for v in c['Config']['Env'])
ip=next(v['IPAddress'] for v in c['NetworkSettings']['Networks'].values() if v['IPAddress'])
p='/internal/v1/search'; ts=str(int(time.time()))
sig=hmac.new(env['INTERNAL_SECRET'].encode(),(ts+'\\nGET\\n'+p).encode(),hashlib.sha256).hexdigest()
u='http://'+ip+':8080'+p+'?'+urllib.parse.urlencode({'q':sys.argv[2],'limit':20,'offset':0,'mode':'simple','personalized':'false'})
with urllib.request.urlopen(urllib.request.Request(u,headers={'X-Vidra-Internal-Auth':'v1:'+ts+':'+sig}),timeout=15) as r: print(r.read().decode())
`, searchContainer, title]));
  assert.ok(result.internal_search.ids.some(hit => hit.video_id === id));
  await watch.goto('/');
  const searchRequests = () => Number(host(['python3', '-c', `
import json,subprocess,sys,urllib.request
c=json.loads(subprocess.check_output(['docker','inspect',sys.argv[1]]))[0]
ip=next(v['IPAddress'] for v in c['NetworkSettings']['Networks'].values() if v['IPAddress'])
with urllib.request.urlopen('http://'+ip+':8080/metrics',timeout=15) as r:
 lines=r.read().decode().splitlines()
values=[float(line.rsplit(' ',1)[1]) for line in lines if line.startswith('vidra_search_http_requests_total{') and 'method="GET"' in line and 'route="/internal/v1/search"' in line and 'status_class="2xx"' in line]
print(sum(values))
`, searchContainer]));
  // This isolated host has no other query clients. Observe the real search
  // service around the unmodified UI request; a local SQL fallback cannot
  // increment vidra-search's successful /internal/v1/search request counter.
  result.ui_search = { service_requests_before: searchRequests() };
  const waitForSearch = () => watch.waitForResponse(r => {
    const url = new URL(r.url());
    return url.pathname === '/api/v1/videos/search' && url.searchParams.get('q') === title;
  });
  let pendingSearch = waitForSearch();
  const box = watch.getByRole('combobox', { name: /Search/ });
  await box.fill(title); await box.press('Enter');
  let uiResponse;
  result.ui_search.attempts = [];
  for (let attempt = 0; attempt < 3; attempt++) {
    uiResponse = await pendingSearch;
    const retryAfter = await uiResponse.headerValue('retry-after');
    result.ui_search.attempts.push({ status: uiResponse.status(), retry_after: retryAfter }); checkpoint();
    if (uiResponse.status() !== 429 || attempt === 2) break;
    const seconds = Number(retryAfter);
    assert.ok(Number.isFinite(seconds) && seconds >= 1 && seconds <= 120, 'invalid Retry-After');
    // The entire fresh-owner/upload/media audit can exhaust one IP's minute
    // budget. Preserve the 429 and obey its wait; never disable/reset limits.
    await new Promise(resolve => setTimeout(resolve, (seconds + 1) * 1000));
    pendingSearch = waitForSearch(); await watch.reload();
  }
  assert.equal(uiResponse.status(), 200);
  result.ui_search.video_ids = (await uiResponse.json()).videos.map(v => v.id);
  assert.ok(result.ui_search.video_ids.includes(id));
  await expect(watch).toHaveURL(/\/search\?q=/);
  const link = watch.getByRole('link', { name: title, exact: true }).first(); await expect(link).toBeVisible();
  result.search_href = await link.getAttribute('href');
  await poll(() => {
    result.ui_search.service_requests_after = searchRequests();
    assert.ok(result.ui_search.service_requests_after > result.ui_search.service_requests_before);
  });
  // The shipped UI declares client-owned query telemetry, suppressing the
  // server's duplicate event (and therefore its source field). Reuse A09's
  // additional browser fetch without that declaration for source=search proof;
  // the counter above independently proves the actual UI request used search.
  const queryMarker = Number(sql('SELECT COALESCE(max(id),0) FROM search_outbox'));
  result.routed_search = await watch.evaluate(async query => {
    const r = await fetch(`/api/v1/videos/search?q=${encodeURIComponent(query)}`);
    return { status: r.status, video_ids: (await r.json()).videos.map(v => v.id) };
  }, title);
  assert.equal(result.routed_search.status, 200); assert.ok(result.routed_search.video_ids.includes(id));
  await poll(() => {
    const row = sql(`SELECT row_to_json(e) FROM (SELECT id,event_id,payload->>'source' AS source FROM search_outbox WHERE id>${queryMarker} AND event_type='search.submitted' AND payload->>'query'='${title}' AND payload->>'source' IS NOT NULL ORDER BY id DESC LIMIT 1) e`);
    result.search_route = row ? JSON.parse(row) : null; assert.equal(result.search_route?.source, 'search');
  });
  await watch.screenshot({ path: join(stage, 'search-result.png') });
  await link.click(); await expect(watch).toHaveURL(new RegExp(`/videos/${id}|/v/`));
  await expect(watch.getByRole('heading', { name: title, exact: true })).toBeVisible();
  // Resolve a short href by the same detail ID, not just a coincidental title.
  assert.equal((await api(`/api/v1/videos/${id}`)).body.id, id);
  result.checks[phase] = 'PASS'; result.status = 'PASS';
} catch (error) {
  result.status = 'FAIL'; result.failed_phase = phase;
  writeFileSync(join(stage, 'private/browser-error.txt'), String(error.stack), { mode: 0o600 });
} finally {
  await browser?.close();
  result.screenshots = {};
  for (const name of ['owner-claimed.png', 'upload-published.png', 'playback-advancing.png', 'search-result.png']) {
    try { result.screenshots[name] = hash(readFileSync(join(stage, name))); } catch { /* absence is explicit in failed results */ }
  }
  checkpoint();
}
console.log(`[release-browser] ${result.status}; phase=${phase}`);
process.exitCode = result.status === 'PASS' ? 0 : 1;
