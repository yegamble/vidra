#!/usr/bin/env node
// Remaining A04 cases; every case records its own outcome, without route mocks.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateTarget, checkCookieSession } from './owner-auth-smoke.mjs';

const [a03dir, actorsDir, output] = process.argv.slice(2);
assert.ok(a03dir && actorsDir && output, 'usage: auth-policies-smoke.mjs A03_OUTPUT A04_ACTORS NEW_OUTPUT');
assert.ok(Number(process.versions.node.split('.')[0]) >= 24);
const vm = readFileSync(join(a03dir, 'vm-name.txt'), 'utf8').trim();
const a03 = JSON.parse(readFileSync(join(a03dir, 'result.json')));
validateTarget(vm, a03);
const actors = JSON.parse(readFileSync(join(actorsDir, 'private-accounts.json')));
mkdirSync(output, { mode: 0o700 });
const selected = (process.env.A04_CASES ?? 'approval-rejection,concurrent-tabs,logout-all-revocation').split(',');
assert.ok(selected.length && selected.every(name => ['approval-rejection', 'concurrent-tabs', 'logout-all-revocation'].includes(name)));
const result = { selected_cases: selected, status: 'UNVERIFIED', checks: {}, project: a03.project, vm,
  helper_sha256: createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex') };
const host = args => execFileSync('multipass', args, { encoding: 'utf8', timeout: 600000, maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
const guest = args => host(['exec', vm, '--', 'sudo', ...args]);
const sql = query => guest(['docker', 'exec', `${a03.project}-postgres-1`, 'psql', '-U', 'vidra', '-d', 'vidra', '-At', '-v', 'ON_ERROR_STOP=1', '-c', query]).trim();
let executed = 0;
const group = async (name, fn) => {
  if (!selected.includes(name)) return;
  if (executed++ > 0) {
    console.log('[a04] allow the production rate-limit window to expire between cases');
    for (let i = 0; i < 2; i++) await new Promise(resolve => setTimeout(resolve, 31000));
  }
  console.log(`[a04] ${name}`);
  try { await fn(); result.checks[name] = 'PASS'; }
  catch (error) {
    result.checks[name] = 'FAIL';
    writeFileSync(join(output, `private-${name}.txt`), error.stack, { mode: 0o600 });
  }
};
const api = (page, path, method = 'GET', body, bearer) => page.evaluate(async data => {
  const res = await fetch(data.path, { method: data.method, credentials: 'include', headers: {
    ...(data.body ? { 'Content-Type': 'application/json' } : {}),
    ...(data.bearer ? { Authorization: `Bearer ${data.bearer}` } : {}) },
    ...(data.body ? { body: JSON.stringify(data.body) } : {}) });
  const text = await res.text();
  return { status: res.status, body: text ? JSON.parse(text) : null };
}, { path, method, body, bearer });
const require = createRequire(resolve('vidra-user/package.json'));
const { chromium, expect } = require('@playwright/test');
host(['start', vm]);
const info = JSON.parse(host(['info', vm, '--format', 'json'])).info[vm];
const ip = info.ipv4.find(value => value.startsWith('192.168.'));
assert.ok(ip);
const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP secure.video.test ${ip}`, '--no-proxy-server'] });
result.browser = browser.version();
const contexts = [];
const newPage = async () => {
  const context = await browser.newContext({ baseURL: 'https://secure.video.test', ignoreHTTPSErrors: true });
  contexts.push(context);
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  await page.goto('/login');
  return page;
};
const login = async (page, actor) => {
  await page.goto('/login');
  await page.getByLabel('Email or username', { exact: true }).fill(actor.email);
  await page.getByLabel('Password', { exact: true }).fill(actor.password);
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/login') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const reply = await response;
  assert.equal(reply.status(), 200);
  await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible();
  return reply.json();
};
try {
  const ownerPage = await newPage();
  const owner = await login(ownerPage, actors.owner);
  checkCookieSession(owner, actors.owner.username, 'admin');
  await group('approval-rejection', async () => {
    const patch = { registration_enabled: true, registration_require_approval: true };
    assert.equal((await api(ownerPage, '/api/v1/admin/instance-settings', 'PATCH', patch, owner.token)).status, 200);
    const pending = [];
    for (const disposition of ['approved', 'rejected']) {
      const id = randomBytes(5).toString('hex');
      const password = randomBytes(24).toString('hex');
      const actor = { username: `pending${id}`, email: `pending${id}@example.test`, password };
      pending.push(actor);
      writeFileSync(join(output, 'private-pending-actors.json'), JSON.stringify(pending), { mode: 0o600 });
      const page = await newPage();
      await page.goto('/signup');
      await page.getByLabel('Username', { exact: true }).fill(actor.username);
      await page.getByLabel('Email', { exact: true }).fill(actor.email);
      await page.getByLabel('Password', { exact: true }).fill(actor.password);
      const response = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/register') && r.request().method() === 'POST');
      await page.getByRole('button', { name: 'Create account', exact: true }).click();
      assert.equal((await response).status(), 202);
      await expect(page.getByText('Your account is awaiting approval')).toBeVisible();
      assert.equal(sql(`SELECT count(*) FROM users WHERE username='${actor.username}'`), '0');
      assert.equal((await api(page, '/api/v1/auth/login', 'POST', { email: actor.email, password: actor.password })).status, 401);
      await ownerPage.goto('/admin/registration-requests');
      await expect(ownerPage.getByText(actor.email, { exact: true })).toBeVisible();
      const verb = disposition === 'approved' ? 'Approve' : 'Reject';
      if (verb === 'Reject') await ownerPage.getByLabel(`Internal note for ${actor.username}`).fill('Synthetic rejection');
      const resolved = ownerPage.waitForResponse(r => r.url().endsWith(`/${verb.toLowerCase()}`) && r.request().method() === 'POST');
      await ownerPage.getByRole('button', { name: `${verb} ${actor.username}`, exact: true }).click();
      assert.equal((await resolved).status(), 204);
      await ownerPage.reload();
      await ownerPage.getByRole('button', { name: 'All', exact: true }).click();
      await expect(ownerPage.getByText(actor.email, { exact: true })).toBeVisible();
      assert.equal(sql(`SELECT status FROM registration_requests WHERE username='${actor.username}'`), disposition);
      assert.equal(sql(`SELECT count(*) FROM users WHERE username='${actor.username}'`), disposition === 'approved' ? '1' : '0');
      if (disposition === 'approved') checkCookieSession(await login(page, actor), actor.username, 'user');
      else assert.equal((await api(page, '/api/v1/auth/login', 'POST', { email: actor.email, password: actor.password })).status, 401);
      await page.context().close();
    }
  });
  // Restore fixture policy even when one approval assertion fails; do not
  // turn a failed acceptance into an implicit configuration change for A06.
  assert.equal((await api(ownerPage, '/api/v1/admin/instance-settings', 'PATCH', { registration_enabled: false, registration_require_approval: false }, owner.token)).status, 200);
  await group('concurrent-tabs', async () => {
    const first = await newPage();
    await login(first, actors.ordinary);
    const second = await first.context().newPage();
    second.setDefaultTimeout(60000);
    await second.goto('/');
    await expect(second.getByRole('button', { name: 'Open account menu' })).toBeVisible();
    const statuses = [];
    for (let i = 0; i < 3; i++) {
      const refreshed = [first, second].map(page => page.waitForResponse(r => r.url().endsWith('/api/v1/auth/refresh')));
      await Promise.all([first.reload(), second.reload()]);
      statuses.push(...(await Promise.all(refreshed)).map(r => r.status()));
      result.concurrent_refresh_statuses = statuses;
      await expect(first.getByRole('button', { name: 'Open account menu' })).toBeVisible();
      await expect(second.getByRole('button', { name: 'Open account menu' })).toBeVisible();
    }
    assert.deepEqual(statuses, [200, 200, 200, 200, 200, 200]);
    result.concurrent_refresh_statuses = statuses;
    await first.getByRole('button', { name: 'Open account menu' }).click();
    const loggedOut = first.waitForResponse(r => r.url().endsWith('/api/v1/auth/logout'));
    await first.getByRole('dialog', { name: 'Account menu' }).getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(first.getByRole('button', { name: 'Open account menu' })).toHaveCount(0);
    assert.equal((await loggedOut).status(), 204);
    const anonymous = second.waitForResponse(r => r.url().endsWith('/api/v1/auth/refresh'));
    await second.reload();
    const missing = await anonymous;
    assert.equal(missing.status(), 422);
    const error = (await missing.json()).error;
    assert.equal(error.code, 'unprocessable_entity');
    assert.ok(error.fields.some(field => field.field === 'refresh_token'));
    assert.equal((await first.context().cookies()).filter(cookie => cookie.name === 'vidra_refresh').length, 0);
    await expect(second.getByRole('button', { name: 'Open account menu' })).toHaveCount(0);
    await first.context().close();
  });
  await group('logout-all-revocation', async () => {
    const page = await newPage();
    const body = { email: actors.ordinary.email, password: actors.ordinary.password };
    const a = await api(page, '/api/v1/auth/login', 'POST', body);
    const b = await api(page, '/api/v1/auth/login', 'POST', body);
    assert.equal(a.status, 200); assert.equal(b.status, 200);
    assert.equal((await api(page, '/api/v1/auth/logout-all', 'POST', undefined, a.body.token)).status, 204);
    for (const session of [a, b]) {
      assert.equal((await api(page, '/api/v1/auth/refresh', 'POST', { refresh_token: session.body.refresh_token })).status, 401);
    }
    await page.context().close();
  });
} catch (error) {
  result.checks.setup_or_cleanup = 'FAIL';
  writeFileSync(join(output, 'private-setup.txt'), error.stack, { mode: 0o600 });
} finally {
  await browser.close();
  result.status = Object.values(result.checks).length === selected.length && Object.values(result.checks).every(v => v === 'PASS') ? 'PASS' : 'FAIL';
  writeFileSync(join(output, 'result.json'), JSON.stringify(result, null, 2) + '\n');
}
console.log(`[a04] ${result.status}; ${output}`);
process.exitCode = result.status === 'PASS' ? 0 : 1;
