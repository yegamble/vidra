#!/usr/bin/env node
// Published-frontend acceptance for peertube_fixture_database.py's ten cases.
// Usage: node tests/b2-migration-browser.mjs PRIVATE_INPUT NEW_OUTPUT_DIRECTORY
// Input: {api_origin,frontend_origin,owner:{email,password},alice:{email,password},
// bob:{email,password},videos:{public:{id},unlisted:{id},...all ten cases}}.
// Run after the separate harness has proved the source is disconnected. This
// driver proves browser/API behavior; it does not itself establish that fact.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

process.umask(0o077);
const [inputArg, outputArg] = process.argv.slice(2);
assert.ok(inputArg && outputArg, 'private input and new output directory required');
const input = JSON.parse(readFileSync(resolve(inputArg), 'utf8'));
for (const key of ['api_origin', 'frontend_origin']) {
  const url = new URL(input[key]);
  assert.ok(['http:', 'https:'].includes(url.protocol) && !url.username && !url.password);
  assert.equal(url.pathname, '/');
}
const cases = ['public', 'unlisted', 'private', 'internal', 'password', 'draft',
  'hls_only', 'split_audio', 'blacklisted', 'missing_media'];
for (const name of cases) assert.match(input.videos[name].id, /^[a-f0-9-]{36}$/);
const output = resolve(outputArg);
mkdirSync(output, { mode: 0o700 }); // Never overwrite an earlier attempt.
const packageFile = process.env.B2_BROWSER_PACKAGE ?? resolve(
  dirname(fileURLToPath(import.meta.url)), '../../vidra-user/package.json');
const { chromium, expect, request } = createRequire(packageFile)('@playwright/test');
const result = {
  status: 'UNVERIFIED', started_at: new Date().toISOString(), checks: {}, requests: [],
  scope: 'Synthetic importer query subset; browser proof requires separate source-disconnection and image-digest evidence.',
  tool_sha256: createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex'),
  node: process.version, browser_package: createRequire(packageFile)('@playwright/test/package.json').version,
};
let browser, phase = 'api-login';
const clients = [];
const save = () => writeFileSync(join(output, 'result.json'), JSON.stringify(result, null, 2) + '\n', { mode: 0o600 });
const client = async () => {
  const value = await request.newContext({ baseURL: input.api_origin });
  clients.push(value); return value;
};
const api = async (context, path, { token, data, method = 'GET' } = {}) => {
  for (let attempt = 0; attempt < 4; attempt++) {
    const response = await context.fetch(path, {
      method, headers: token ? { Authorization: `Bearer ${token}` } : {}, data, timeout: 60000,
    });
    result.requests.push({ path: path.split('?')[0], method, status: response.status() }); save();
    if (response.status() !== 429) return response;
    const seconds = Number(response.headers()['retry-after']);
    assert.ok(seconds > 0 && seconds <= 120, 'bounded rate-limit retry required');
    await new Promise(done => setTimeout(done, (seconds + 1) * 1000));
  }
  throw new Error('request remained rate limited');
};
const login = async (who, expected) => {
  const context = await client();
  const response = await api(context, '/api/v1/auth/login', {
    method: 'POST', data: { email: input[who].email, password: input[who].password },
  });
  assert.equal(response.status(), expected, `${who} login status`);
  if (expected !== 200) return { context };
  const auth = await response.json(); assert.ok(auth.token);
  return { context, token: auth.token };
};
try {
  const anon = await client();
  const alice = await login('alice', 200);
  await login('bob', 403);
  const owner = await login('owner', 200);
  result.checks.imported_login_and_suspension = 'PASS';

  phase = 'visibility';
  const mediaStatus = { public: 200, unlisted: 200, private: 404, internal: 401,
    password: 404, draft: 404, hls_only: 404, split_audio: 404, blacklisted: 404, missing_media: 404 };
  for (const name of cases) {
    const path = `/api/v1/videos/${input.videos[name].id}`;
    const response = await api(anon, path + '/original');
    assert.equal(response.status(), mediaStatus[name], `${name} anonymous media`);
    if (name === 'internal') assert.equal((await response.json()).error.code, 'sign_in_required');
    const detail = await api(anon, path);
    const expected = ['private', 'password', 'blacklisted'].includes(name) ? 404 : name === 'internal' ? 401 : 200;
    assert.equal(detail.status(), expected, `${name} anonymous detail`);
  }
  for (const name of ['private', 'password', 'internal', 'draft']) {
    const response = await api(alice.context, `/api/v1/videos/${input.videos[name].id}/original`, { token: alice.token });
    assert.equal(response.status(), 200, `${name} owning account media`);
  }
  assert.equal((await api(alice.context, `/api/v1/videos/${input.videos.blacklisted.id}/original`, { token: alice.token })).status(), 404);
  assert.equal((await api(owner.context, `/api/v1/videos/${input.videos.internal.id}/original`, { token: owner.token })).status(), 200);
  for (const name of ['private', 'password']) {
    assert.equal((await api(owner.context, `/api/v1/videos/${input.videos[name].id}/original`, { token: owner.token })).status(), 404);
  }
  result.checks.access_controls = 'PASS';

  phase = 'artwork-captions-search';
  const publicPath = `/api/v1/videos/${input.videos.public.id}`;
  for (const suffix of ['/thumbnail', '/storyboard.jpg']) {
    const response = await api(anon, publicPath + suffix);
    assert.equal(response.status(), 200);
    assert.match(response.headers()['content-type'], /^image\//);
    assert.ok((await response.body()).length > 100);
  }
  for (const suffix of ['/storyboard.vtt', '/captions/en']) {
    const response = await api(anon, publicPath + suffix);
    assert.equal(response.status(), 200); assert.match(await response.text(), /^WEBVTT/);
  }
  const chapters = await api(anon, publicPath + '/chapters');
  assert.equal(chapters.status(), 200);
  const chapterBody = await chapters.json();
  assert.equal((chapterBody.chapters ?? chapterBody).length, 2);
  const search = await api(anon, '/api/v1/videos/search?q=Synthetic&limit=100');
  assert.equal(search.status(), 200);
  const hits = await search.json();
  assert.deepEqual(hits.videos.map(video => video.id).sort(),
    ['public', 'hls_only', 'split_audio', 'missing_media'].map(name => input.videos[name].id).sort());
  assert.equal(typeof hits.search_total, 'number', 'real search-service response required');
  result.checks.assets_and_search = 'PASS';

  phase = 'browser-start';
  browser = await chromium.launch({
    ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
    args: ['--no-proxy-server', '--autoplay-policy=no-user-gesture-required'],
  });
  result.browser = browser.version(); result.browser_executable_override = Boolean(process.env.CHROMIUM_PATH);
  const context = await browser.newContext({ baseURL: input.frontend_origin,
    viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage(); page.setDefaultTimeout(60000);
  let mediaResponses = [];
  page.on('response', response => {
    const path = new URL(response.url()).pathname;
    if (/\/api\/v1\/videos\/[^/]+\/(hls\/|original)/.test(path)) {
      mediaResponses.push({ path, status: response.status() });
    }
  });
  result.playback = [];
  const sample = video => video.evaluate(element => ({ time: element.currentTime,
    frames: element.getVideoPlaybackQuality().totalVideoFrames,
    audio_bytes: element.webkitAudioDecodedByteCount ?? null,
    error: element.error?.code ?? null, width: element.videoWidth, height: element.videoHeight }));
  const decode = async (video, name) => {
    await expect(async () => assert.ok(await video.evaluate(element => element.readyState >= 2))).toPass({ timeout: 90000 });
    await video.evaluate(element => { element.pause(); element.currentTime = 0; element.muted = false; });
    const start = await sample(video);
    assert.equal(typeof start.audio_bytes, 'number', 'browser must expose audio decode evidence');
    await video.evaluate(element => element.play());
    let end;
    await expect(async () => {
      end = await sample(video); assert.equal(end.error, null);
      assert.ok(end.time - start.time >= 1.5 && end.frames > start.frames && end.audio_bytes > start.audio_bytes);
      assert.ok(end.width > 0 && end.height > 0);
    }).toPass({ timeout: 60000, intervals: [250, 500, 1000] });
    await video.evaluate(element => element.pause());
    result.playback.push({ name, start, end }); save();
  };
  phase = 'published-watch-playback';
  for (const name of ['public', 'hls_only', 'split_audio']) {
    mediaResponses = [];
    await page.goto(`/videos/${input.videos[name].id}`);
    await expect(page.getByRole('heading', { name: `Synthetic ${name}`, exact: true })).toBeVisible();
    const video = page.getByTestId('video-player').first().locator('video');
    await decode(video, name);
    assert.ok(mediaResponses.some(item => item.path.endsWith('/hls/master.m3u8') && item.status === 200), 'watch page must use imported HLS');
    assert.ok(mediaResponses.some(item => /\.(m4s|mp4)$/.test(item.path) && item.status === 200), 'HLS media dependency must load');
    if (name === 'split_audio') assert.ok(mediaResponses.some(item =>
      /audio.*\.(m4s|mp4)$/.test(item.path) && item.status === 200), 'separate audio dependency must load');
    result.playback.at(-1).media_responses = [...mediaResponses];
    const seek = page.getByRole('slider', { name: 'Seek', exact: true });
    const box = await seek.boundingBox(); assert.ok(box);
    await seek.click({ position: { x: box.width * 0.6, y: box.height / 2 } });
    await expect(async () => assert.ok(await video.evaluate(element =>
      element.currentTime >= 2 && element.currentTime < 3.5))).toPass({ timeout: 15000 });
    if (name === 'public') {
      await page.getByRole('button', { name: 'Captions', exact: true }).click();
      await expect(async () => assert.ok(await video.evaluate(element =>
        [...element.textTracks].some(track => track.mode !== 'disabled' && track.cues?.length > 0)))).toPass({ timeout: 15000 });
      await seek.hover({ position: { x: box.width * 0.8, y: box.height / 2 } });
      const sprite = seek.locator('[style*="storyboard.jpg"]');
      await expect(sprite).toBeVisible();
      assert.ok(await sprite.evaluate(async element => {
        const url = getComputedStyle(element).backgroundImage.match(/^url\(["']?(.*?)["']?\)$/)?.[1];
        if (!url) return false;
        const image = new Image(); image.src = url; await image.decode();
        return image.naturalWidth > 0 && image.naturalHeight > 0;
      }));
    }
    await page.screenshot({ path: join(output, `${name}.png`) });
    await page.reload();
    await expect(page.getByRole('heading', { name: `Synthetic ${name}`, exact: true })).toBeVisible();
  }
  result.checks.watch_decode_audio_seek_reload = 'PASS';

  phase = 'progressive-original-decode';
  await page.goto(`/videos/${input.videos.public.id}`);
  await page.evaluate(url => {
    const element = document.createElement('video'); element.id = 'acceptance-original';
    element.src = url; element.preload = 'auto'; document.body.append(element);
  }, input.api_origin + publicPath + '/original');
  await decode(page.locator('#acceptance-original'), 'progressive-original');
  result.checks.progressive_original_decode = 'PASS';

  phase = 'persisted-admin-report';
  await page.goto('/login');
  await page.getByLabel('Email or username', { exact: true }).fill(input.owner.email);
  await page.getByLabel('Password', { exact: true }).fill(input.owner.password);
  const loginResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/auth/login'
    && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  assert.equal((await loginResponse).status(), 200);
  await page.goto('/admin/import-peertube');
  await expect(page.getByRole('heading', { name: 'Import from PeerTube', exact: true })).toBeVisible();
  const report = page.getByRole('region', { name: 'Import run', exact: true });
  await expect(report).toBeVisible();
  await expect(report.getByText('Done', { exact: true })).toBeVisible();
  await expect(report.getByText('PeerTube schema v1040', { exact: true })).toBeVisible();
  await page.screenshot({ path: join(output, 'persisted-admin-report.png') });
  result.checks.persisted_admin_report = 'PASS';
  result.status = 'PASS';
} catch (error) {
  result.status = 'FAIL'; result.failed_phase = phase;
  writeFileSync(join(output, 'private-error.txt'), String(error.stack), { mode: 0o600 });
} finally {
  await browser?.close(); await Promise.all(clients.map(context => context.dispose()));
  result.finished_at = new Date().toISOString(); save();
}
console.log(JSON.stringify({ status: result.status, failed_phase: result.failed_phase }));
process.exitCode = result.status === 'PASS' ? 0 : 1;
