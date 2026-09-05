#!/usr/bin/env node
// A04 browser/API/SQL proof against the retained disposable A03 stack only.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export function validateTarget(vm, result) {
  assert.match(vm, /^vidra-a02-\d+-\d+$/);
  assert.equal(result.status, 'PASS');
  assert.equal(result.checks.recovery, 'PASS');
  assert.match(result.project, /^vidra-a03-\d+-\d+$/);
}
export function checkIdentity(user, username, role) {
  assert.ok(user?.id);
  assert.equal(user.username, username);
  assert.equal(user.role, role);
}

export function checkCookieSession(auth, username, role) {
  assert.ok(typeof auth.token === 'string' && auth.token.length > 0, 'missing contract token field');
  assert.equal(auth.refresh_token, undefined, 'cookie-mode refresh token exposed in body');
  checkIdentity(auth.user, username, role);
}

async function main() {
  assert.ok(Number(process.versions.node.split('.')[0]) >= 24, 'Node >=24 required');
  const [a03dir, output] = process.argv.slice(2);
  assert.ok(a03dir && output, 'usage: owner-auth-smoke.mjs A03_OUTPUT NEW_OUTPUT');
  const vm = readFileSync(join(a03dir, 'vm-name.txt'), 'utf8').trim();
  const a03bytes = readFileSync(join(a03dir, 'result.json'));
  const a03 = JSON.parse(a03bytes);
  validateTarget(vm, a03);
  mkdirSync(output, { mode: 0o700 }); // existing output must never be overwritten
  const evidence = { status: 'UNVERIFIED', checks: {},
    a03_sha256: createHash('sha256').update(a03bytes).digest('hex'),
    helper_sha256: createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex'),
    project: a03.project, vm, node: process.version };
  let phase = 'preconditions';
  const step = name => { phase = name; console.log(`[a04] ${name}`); };
  const host = args => execFileSync('multipass', args, { encoding: 'utf8', timeout: 360000, maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
  const guest = args => host(['exec', vm, '--', 'sudo', ...args]);
  const sql = query => guest(['docker', 'exec', `${a03.project}-postgres-1`, 'psql', '-U', 'vidra', '-d', 'vidra', '-At', '-v', 'ON_ERROR_STOP=1', '-c', query]).trim();
  const token = () => {
    const logs = guest(['docker', 'logs', `${a03.project}-api-1`]);
    const matches = [...logs.matchAll(/403 owner_claim_required until claimed\): ([A-Za-z0-9_-]+)/g)];
    assert.ok(matches.length, 'missing boot token');
    return matches.at(-1)[1];
  };
  let browser;
  try {
    host(['start', vm]);
    assert.equal(sql('SELECT count(*) FROM users'), '0', 'requires an unclaimed rehearsal; do not erase accounts');
    step('open-unclaimed-fixture');
    const root = `/home/ubuntu/${a03.project}/private/installation`;
    guest(['sh', '-c', `cd ${root} && vidra setup --non-interactive --yes --registration open --template env/production.env.example`]);
    guest(['sh', '-c', `cd ${root} && env COMPOSE_PROJECT_NAME=${a03.project} API_CPUS=2.0 API_MEM_LIMIT=1536m READY_TIMEOUT=300 bash deploy/deploy.sh`]);
    const info = JSON.parse(host(['info', vm, '--format', 'json'])).info[vm];
    const ip = info.ipv4.find(value => value.startsWith('192.168.'));
    assert.ok(ip, 'missing VM LAN address');
    const require = createRequire(resolve('vidra-user/package.json'));
    const { chromium, expect } = require('@playwright/test');
    browser = await chromium.launch({ args: [`--host-resolver-rules=MAP secure.video.test ${ip}`, '--no-proxy-server'] });
    evidence.browser = browser.version();
    const context = await browser.newContext({ baseURL: 'https://secure.video.test', ignoreHTTPSErrors: true });
    const page = await context.newPage();
    page.setDefaultTimeout(60000);
    const api = (path, method = 'GET', body, bearer) => page.evaluate(async ({ path, method, body, bearer }) => {
      const res = await fetch(path, { method, credentials: 'include', headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}), ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}) });
      const text = await res.text();
      return { status: res.status, body: text ? JSON.parse(text) : null };
    }, { path, method, body, bearer });
    const id = randomBytes(5).toString('hex');
    const account = name => ({ username: `${name}${id}`, email: `${name}${id}@example.test`, password: `A04-${randomBytes(20).toString('hex')}` });
    const owner = account('owner'), ordinary = account('viewer');
    writeFileSync(join(output, 'private-accounts.json'), JSON.stringify({ owner, ordinary }), { mode: 0o600 });
    const ownerToken = token();
    await page.goto('/setup/claim');
    assert.equal((await api('/api/v1/instance')).body.owner_claim_pending, true);
    step('preclaim-refusal-and-token-rotation');
    const denied = await api('/api/v1/auth/register', 'POST', ordinary);
    assert.equal(denied.status, 403);
    assert.equal(denied.body.error.code, 'owner_claim_required');
    guest(['docker', 'restart', `${a03.project}-api-1`]);
    await expect.poll(async () => {
      try { return (await api('/readyz')).status; } catch { return 0; }
    }, { timeout: 180000 }).toBe(200);
    const rotated = token();
    assert.notEqual(rotated, ownerToken);
    for (const value of [ownerToken, 'invalid-a04-claim-token']) {
      const rejected = await api('/api/v1/setup/claim-owner', 'POST', { ...owner, token: value });
      assert.equal(rejected.status, 403);
      assert.equal(rejected.body.error.code, 'owner_claim_invalid');
    }
    assert.equal(sql('SELECT count(*) FROM users'), '0');
    evidence.checks.preclaim_rotation = 'PASS';
    step('browser-owner-claim');
    await page.reload();
    await page.getByLabel('Setup token').fill(rotated);
    await page.getByLabel('Username', { exact: true }).fill(owner.username);
    await page.getByLabel('Email', { exact: true }).fill(owner.email);
    await page.getByLabel('Password', { exact: true }).fill(owner.password);
    await page.getByLabel('Confirm password', { exact: true }).fill(owner.password);
    const claimed = page.waitForResponse(r => r.url().endsWith('/api/v1/setup/claim-owner') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Create the owner account' }).click();
    const response = await claimed;
    assert.equal(response.status(), 201);
    const auth = await response.json();
    checkCookieSession(auth, owner.username, 'admin');
    await expect(page.getByRole('heading', { name: 'Your server is ready' })).toBeVisible();
    await page.getByRole('link', { name: 'Go to the home page' }).click();
    await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible();
    checkIdentity((await api('/api/v1/auth/me', 'GET', undefined, auth.token)).body, owner.username, 'admin');
    assert.equal((await api('/api/v1/admin/system', 'GET', undefined, auth.token)).status, 200);
    assert.equal((await api('/api/v1/instance')).body.owner_claim_pending, false);
    assert.equal(sql("SELECT count(*) FROM users WHERE role = 'admin'"), '1');
    assert.equal((await api('/api/v1/setup/claim-owner', 'POST', { ...ordinary, token: rotated })).status, 403);
    evidence.checks.owner_claim_role = 'PASS';
    step('open-registration-and-browser-signup');
    assert.equal((await api('/api/v1/admin/instance-settings', 'PATCH', { registration_enabled: true }, auth.token)).status, 200);
    const visitor = await browser.newContext({ baseURL: 'https://secure.video.test', ignoreHTTPSErrors: true });
    const userPage = await visitor.newPage();
    userPage.setDefaultTimeout(60000);
    await userPage.goto('/signup');
    await userPage.getByLabel('Username', { exact: true }).fill(ordinary.username);
    await userPage.getByLabel('Email', { exact: true }).fill(ordinary.email);
    await userPage.getByLabel('Password', { exact: true }).fill(ordinary.password);
    const signup = userPage.waitForResponse(r => r.url().endsWith('/api/v1/auth/register') && r.request().method() === 'POST');
    await userPage.getByRole('button', { name: 'Create account', exact: true }).click();
    const signed = await signup;
    assert.equal(signed.status(), 201);
    const userAuth = await signed.json();
    checkCookieSession(userAuth, ordinary.username, 'user');
    await expect(userPage.getByRole('button', { name: 'Open account menu' })).toBeVisible();
    assert.equal((await api('/api/v1/admin/system', 'GET', undefined, userAuth.token)).status, 403);
    assert.equal(sql("SELECT count(*) FROM users WHERE role = 'user'"), '1');
    evidence.checks.ordinary_signup_role = 'PASS';
    step('session-reload-logout-login');
    for (let i = 0; i < 2; i++) {
      const refresh = userPage.waitForResponse(r => r.url().endsWith('/api/v1/auth/refresh'));
      await userPage.reload();
      const renewed = await refresh;
      assert.equal(renewed.status(), 200);
      checkCookieSession(await renewed.json(), ordinary.username, 'user');
      await expect(userPage.getByRole('button', { name: 'Open account menu' })).toBeVisible();
    }
    const cookie = (await visitor.cookies()).find(c => c.name === 'vidra_refresh');
    assert.ok(cookie?.httpOnly && cookie?.secure, 'refresh cookie must be protected');
    await userPage.getByRole('button', { name: 'Open account menu' }).click();
    await userPage.getByRole('dialog', { name: 'Account menu' }).getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(userPage.getByRole('button', { name: 'Open account menu' })).toHaveCount(0);
    await userPage.reload();
    await expect(userPage.getByRole('button', { name: 'Open account menu' })).toHaveCount(0);
    assert.equal((await visitor.cookies()).filter(c => c.name === 'vidra_refresh').length, 0);
    await userPage.goto('/login');
    await userPage.getByLabel('Email or username', { exact: true }).fill(ordinary.email);
    await userPage.getByLabel('Password', { exact: true }).fill(ordinary.password);
    const login = userPage.waitForResponse(r => r.url().endsWith('/api/v1/auth/login') && r.request().method() === 'POST');
    await userPage.getByRole('button', { name: 'Sign in', exact: true }).click();
    const logged = await login;
    assert.equal(logged.status(), 200);
    checkCookieSession(await logged.json(), ordinary.username, 'user');
    await expect(userPage.getByRole('button', { name: 'Open account menu' })).toBeVisible();
    evidence.checks.session_persistence = 'PASS';
    step('rejected-login-and-closed-registration');
    const wrong = await api('/api/v1/auth/login', 'POST', { email: ordinary.email, password: 'wrong-a04-password' });
    assert.equal(wrong.status, 401);
    assert.ok(!wrong.body.token && !wrong.body.refresh_token);
    assert.equal((await api('/api/v1/admin/instance-settings', 'PATCH', { registration_enabled: false }, auth.token)).status, 200);
    assert.equal((await api('/api/v1/auth/register', 'POST', account('closed'))).status, 403);
    assert.equal(sql('SELECT count(*) FROM users'), '2');
    evidence.checks.rejected_auth = 'PASS';
    await userPage.screenshot({ path: join(output, 'signed-in.png') });
    evidence.status = 'PASS';
  } catch (error) {
    evidence.status = 'FAIL';
    evidence.failed_phase = phase;
    // Playwright diagnostics can include filled credentials. Keep details in
    // the private output directory, never in exported acceptance evidence.
    writeFileSync(join(output, 'private-error.txt'), String(error.stack), { mode: 0o600 });
  } finally {
    await browser?.close();
    writeFileSync(join(output, 'result.json'), JSON.stringify(evidence, null, 2) + '\n', { mode: 0o600 });
  }
  console.log(`[a04] ${evidence.status}; evidence in ${output}`);
  process.exitCode = evidence.status === 'PASS' ? 0 : 1;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
