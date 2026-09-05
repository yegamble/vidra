#!/usr/bin/env node
// A06 uses actual browser requests and persisted bytes; never route interception.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateTarget } from './owner-auth-smoke.mjs';
assert.ok(Number(process.versions.node.split('.')[0]) >= 24, 'Node >=24 required');
const [a03dir, actorsDir, fixture, output] = process.argv.slice(2);
assert.ok(output, 'usage: upload-smoke.mjs A03_OUTPUT A04_ACTORS MP4 NEW_OUTPUT');
const a03 = JSON.parse(readFileSync(join(a03dir, 'result.json')));
const vm = readFileSync(join(a03dir, 'vm-name.txt'), 'utf8').trim();
validateTarget(vm, a03);
const actors = JSON.parse(readFileSync(join(actorsDir, 'private-accounts.json')));
const bytes = readFileSync(fixture);
const hash = b => createHash('sha256').update(b).digest('hex');
mkdirSync(output, { mode: 0o700 });
const result = { status: 'UNVERIFIED', checks: {}, node: process.version, vm, project: a03.project,
  helper_sha256: hash(readFileSync(fileURLToPath(import.meta.url))), fixture_sha256: hash(bytes), fixture_bytes: bytes.length };
const host = args => execFileSync('multipass', args, { encoding: 'utf8', timeout: 360000, maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
const guest = args => host(['exec', vm, '--', 'sudo', ...args]);
const sql = query => guest(['docker', 'exec', `${a03.project}-postgres-1`, 'psql', '-U', 'vidra', '-d', 'vidra', '-At', '-v', 'ON_ERROR_STOP=1', '-c', query]).trim();
const uuid = id => { assert.match(id, /^[0-9a-f-]{36}$/); return id; };
host(['start', vm]);
const ip = JSON.parse(host(['info', vm, '--format', 'json'])).info[vm].ipv4.find(v => v.startsWith('192.168.'));
assert.ok(ip);
const { chromium, expect } = createRequire(resolve('vidra-user/package.json'))('@playwright/test');
const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP secure.video.test ${ip}`, '--no-proxy-server'] });
result.browser = browser.version();
let phase = 'setup', restoreQuota;
const step = name => { phase = name; console.log(`[a06] ${name}`); };
const login = async actor => {
  const ctx = await browser.newContext({ baseURL: 'https://secure.video.test', ignoreHTTPSErrors: true });
  const page = await ctx.newPage(); page.setDefaultTimeout(60000);
  await page.goto('/login');
  await page.getByLabel('Email or username', { exact: true }).fill(actor.email);
  await page.getByLabel('Password', { exact: true }).fill(actor.password);
  const pending = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/login') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const response = await pending; assert.equal(response.status(), 200);
  await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible();
  const auth = await response.json(); uuid(auth.user.id);
  return { page, token: auth.token, user: auth.user };
};
const api = (actor, path, method = 'GET', body) => actor.page.evaluate(async ({ path, method, body, token }) => {
  const r = await fetch(path, { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  return { status: r.status, body: r.status === 204 ? null : await r.json() };
}, { path, method, body, token: actor.token });
const originalHash = (actor, id) => actor.page.evaluate(async ({ id, token }) => {
  const r = await fetch(`/api/v1/videos/${id}/original`, { headers: { Authorization: `Bearer ${token}` } });
  const digest = await crypto.subtle.digest('SHA-256', await r.arrayBuffer());
  return { status: r.status, content_type: r.headers.get('content-type'), sha256: Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('') };
}, { id, token: actor.token });

try {
  const creator = await login(actors.ordinary), other = await login(actors.owner);
  const { page } = creator;
  const before = await api(creator, '/api/v1/me/quota'); assert.equal(before.status, 200);
  step('channel-draft-upload');
  const handle = `a06${randomBytes(5).toString('hex')}`;
  await page.getByRole('link', { name: 'Studio', exact: true }).click();
  await page.getByRole('link', { name: 'Channel', exact: true }).click();
  const another = page.getByRole('button', { name: 'Create another channel', exact: true });
  await expect(another.or(page.getByLabel('Channel handle'))).toBeVisible();
  if (await another.isVisible()) await another.click();
  await page.getByLabel('Channel handle').fill(handle);
  await page.getByLabel('Channel display name').fill(`A06 ${handle}`);
  const channelCreated = page.waitForResponse(r => r.url().endsWith('/api/v1/channels') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create channel', exact: true }).click();
  const cr = await channelCreated; assert.equal(cr.status(), 201);
  const channel = await cr.json(); uuid(channel.id);
  result.channel_id = channel.id; result.channel_handle = handle;
  await expect(page.getByRole('dialog', { name: 'Create a channel', exact: true })).toHaveCount(0);
  const switcher = page.getByRole('button', { name: /^Switch channel/ });
  if (await switcher.count()) {
    await switcher.click();
    await page.getByRole('menuitem').filter({ hasText: `@${handle}` }).click();
  }
  await expect(page.getByText(`@${handle}`, { exact: true }).first()).toBeVisible();
  assert.equal(sql(`SELECT owner_id FROM channels WHERE id='${channel.id}'`), creator.user.id);
  await page.getByRole('link', { name: 'Content', exact: true }).click();
  const draftCreated = page.waitForResponse(r => /\/channels\/[^/]+\/videos$/.test(r.url()) && r.request().method() === 'POST');
  const completed = page.waitForResponse(r => /\/uploads\/[^/]+\/complete$/.test(r.url()) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Upload video', exact: true }).click();
  await page.getByLabel('Video file', { exact: true }).setInputFiles({ name: 'a06-clip.mp4', mimeType: 'video/mp4', buffer: bytes });
  const dr = await draftCreated; assert.equal(dr.status(), 201);
  const draft = await dr.json(); uuid(draft.id); result.video_id = draft.id;
  assert.equal(sql(`SELECT channel_id FROM videos WHERE id='${draft.id}'`), channel.id);
  assert.equal(draft.state, 'draft'); assert.equal(draft.privacy, 'private');
  const complete = await completed; assert.equal(complete.status(), 202);
  result.upload_id = (await complete.json()).upload_id;
  await expect(page.getByText('Uploaded', { exact: true })).toBeVisible({ timeout: 180000 });
  const video = await api(creator, `/api/v1/videos/${draft.id}`); assert.equal(video.status, 200);
  assert.equal(video.body.width, 320); assert.equal(video.body.height, 240); assert.equal(video.body.duration_seconds, 5);
  assert.notEqual(video.body.state, 'failed');
  result.video = { state: video.body.state, privacy: video.body.privacy, width: video.body.width, height: video.body.height, duration_seconds: video.body.duration_seconds };
  const original = JSON.parse(sql(`SELECT row_to_json(f) FROM (SELECT size_bytes,content_type,original_name FROM video_files WHERE video_id='${draft.id}' AND kind='original') f`));
  assert.equal(original.size_bytes, bytes.length); assert.equal(original.original_name, 'a06-clip.mp4');
  result.original = original;
  const downloaded = await originalHash(creator, draft.id);
  assert.equal(downloaded.status, 200); assert.equal(downloaded.sha256, hash(bytes));
  assert.equal(downloaded.content_type, 'video/mp4'); result.original_response = downloaded;
  result.checks[phase] = 'PASS';
  step('ownership-invalid-quota');
  const path = `/api/v1/videos/${draft.id}/upload-session`;
  const session = { filename: 'clip.mp4', size: bytes.length };
  assert.equal((await api(other, path, 'POST', session)).status, 404);
  assert.equal((await api(creator, path, 'POST', { ...session, size: 0 })).status, 422);
  assert.equal((await api(creator, path, 'POST', { ...session, filename: 'clip.exe' })).status, 415);
  const originalQuota = sql(`SELECT COALESCE(storage_quota_bytes::text,'null') FROM users WHERE id='${creator.user.id}'`);
  const adminPath = `/api/v1/admin/users/${creator.user.id}`;
  restoreQuota = async () => assert.equal((await api(other, adminPath, 'PATCH', { storage_quota_bytes: JSON.parse(originalQuota) })).status, 200);
  assert.equal((await api(other, adminPath, 'PATCH', { storage_quota_bytes: 1 })).status, 200);
  const rejected = await api(creator, path, 'POST', session);
  assert.equal(rejected.status, 422); assert.equal(rejected.body.error.code, 'quota_exceeded');
  await restoreQuota(); restoreQuota = undefined;
  assert.equal(sql(`SELECT count(*) FROM upload_sessions WHERE video_id='${draft.id}'`), '1');
  result.checks[phase] = 'PASS';
  step('invalid-media');
  await page.reload();
  const badDraftResponse = page.waitForResponse(r => /\/channels\/[^/]+\/videos$/.test(r.url()) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Upload video', exact: true }).click();
  await page.getByLabel('Video file', { exact: true }).setInputFiles({ name: 'a06-invalid.mp4', mimeType: 'video/mp4', buffer: Buffer.from('A06 invalid media fixture') });
  const badDraft = await (await badDraftResponse).json(); uuid(badDraft.id); result.invalid_video_id = badDraft.id;
  await expect(page.getByText('Processing failed — the file could not be published', { exact: false })).toBeVisible({ timeout: 180000 });
  await expect(page.getByText('Published!', { exact: true })).toHaveCount(0);
  assert.equal(sql(`SELECT state FROM videos WHERE id='${badDraft.id}'`), 'failed');
  assert.equal((await originalHash(other, draft.id)).status, 404);
  result.checks[phase] = 'PASS';
  step('durability-accounting');
  // Recreate only the API; this proves rows/files survive container replacement.
  guest(['bash', '-c', `cd /home/ubuntu/${a03.project}/private/installation && env COMPOSE_PROJECT_NAME=${a03.project} API_CPUS=2.0 API_MEM_LIMIT=1536m bash deploy/compose.sh up -d --no-build --no-deps --pull never --force-recreate api`]);
  await expect(async () => assert.equal(await page.evaluate(async () => (await fetch('/readyz')).status), 200)).toPass({ timeout: 180000, intervals: [3000] });
  await page.reload();
  await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible();
  const persisted = await api(creator, `/api/v1/videos/${draft.id}`); assert.equal(persisted.status, 200);
  const again = await originalHash(creator, draft.id);
  assert.equal(again.status, 200); assert.equal(again.sha256, hash(bytes));
  const sumQuery = `SELECT COALESCE(SUM(f.size_bytes),0) FROM video_files f JOIN videos v ON v.id=f.video_id JOIN channels c ON c.id=v.channel_id WHERE c.owner_id='${creator.user.id}'`;
  await expect(async () => {
    const quota = await api(creator, '/api/v1/me/quota'); assert.equal(quota.status, 200);
    assert.equal(quota.body.used_bytes, Number(sql(sumQuery)));
    assert.ok(quota.body.used_bytes >= before.body.used_bytes + bytes.length);
    result.quota = { before: before.body.used_bytes, after: quota.body.used_bytes, sql_sum: Number(sql(sumQuery)) };
  }).toPass({ timeout: 60000, intervals: [3000] });
  await page.screenshot({ path: join(output, 'private-studio.png'), fullPage: true });
  result.checks[phase] = 'PASS'; result.status = 'PASS';
} catch (error) {
  result.checks[phase] = 'FAIL'; result.status = 'FAIL';
  writeFileSync(join(output, 'private-error.txt'), error.stack, { mode: 0o600 });
} finally {
  if (restoreQuota) { try { await restoreQuota(); } catch { result.checks.quota_restoration = 'FAIL'; result.status = 'FAIL'; } }
  await browser.close();
  writeFileSync(join(output, 'result.json'), JSON.stringify(result, null, 2) + '\n');
}
console.log(`[a06] ${result.status}; ${output}`);
process.exitCode = result.status === 'PASS' ? 0 : 1;
