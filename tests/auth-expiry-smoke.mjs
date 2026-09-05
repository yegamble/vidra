#!/usr/bin/env node
// Real elapsed-time expiry, with original deployment settings restored afterward.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import https from 'node:https';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateTarget } from './owner-auth-smoke.mjs';

const [a03dir, actorsDir, output] = process.argv.slice(2);
assert.ok(a03dir && actorsDir && output, 'usage: auth-expiry-smoke.mjs A03_OUTPUT A04_ACTORS NEW_OUTPUT');
const vm = readFileSync(join(a03dir, 'vm-name.txt'), 'utf8').trim();
const a03 = JSON.parse(readFileSync(join(a03dir, 'result.json')));
validateTarget(vm, a03);
const { ordinary } = JSON.parse(readFileSync(join(actorsDir, 'private-accounts.json')));
mkdirSync(output, { mode: 0o700 });
const result = { status: 'UNVERIFIED', checks: {}, project: a03.project, vm,
  helper_sha256: createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex') };
const host = args => execFileSync('multipass', args, { encoding: 'utf8', timeout: 600000, maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
const guest = args => host(['exec', vm, '--', 'sudo', ...args]);
host(['start', vm]);
const ip = JSON.parse(host(['info', vm, '--format', 'json'])).info[vm].ipv4.find(v => v.startsWith('192.168.'));
assert.ok(ip);
const environment = () => Object.fromEntries(JSON.parse(guest(['docker', 'inspect', `${a03.project}-api-1`]))[0].Config.Env.map(v => v.split(/=(.*)/s).slice(0, 2)));
const original = environment();
for (const key of ['JWT_ACCESS_TTL', 'JWT_REFRESH_TTL']) assert.match(original[key], /^[0-9]+[smh]$/);
const deploy = (access, refresh) => {
  const text = guest(['sh', '-c', `cd /home/ubuntu/${a03.project}/private/installation && env COMPOSE_PROJECT_NAME=${a03.project} API_CPUS=2.0 API_MEM_LIMIT=1536m READY_TIMEOUT=300 JWT_ACCESS_TTL=${access} JWT_REFRESH_TTL=${refresh} bash deploy/deploy.sh`]);
  writeFileSync(join(output, `private-deploy-${access}-${refresh}.log`), text, { mode: 0o600 });
};
const request = (path, body, token) => new Promise((resolve, reject) => {
  const req = https.request({ hostname: ip, servername: 'secure.video.test', rejectUnauthorized: false,
    path, method: body ? 'POST' : 'GET', headers: { Host: 'secure.video.test', 'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}) }, timeout: 30000 }, res => {
    let text = '';
    res.on('data', bytes => { text += bytes; });
    res.on('end', () => { try { resolve({ status: res.statusCode, body: text ? JSON.parse(text) : null }); } catch (error) { reject(error); } });
  });
  req.on('error', reject); req.on('timeout', () => req.destroy(new Error('request timeout')));
  req.end(body ? JSON.stringify(body) : undefined);
});
try {
  console.log('[a04] deploy short-lived tokens');
  deploy('6s', '18s');
  const configured = environment();
  assert.equal(configured.JWT_ACCESS_TTL, '6s'); assert.equal(configured.JWT_REFRESH_TTL, '18s');
  const login = () => request('/api/v1/auth/login', { email: ordinary.email, password: ordinary.password });
  const first = await login(), untouched = await login();
  assert.equal(first.status, 200); assert.equal(untouched.status, 200);
  assert.equal(first.body.expires_in, 6);
  assert.equal((await request('/api/v1/auth/me', undefined, first.body.token)).status, 200);
  await new Promise(resolve => setTimeout(resolve, 8500));
  assert.equal((await request('/api/v1/auth/me', undefined, first.body.token)).status, 401);
  const refreshed = await request('/api/v1/auth/refresh', { refresh_token: first.body.refresh_token });
  assert.equal(refreshed.status, 200);
  assert.notEqual(refreshed.body.refresh_token, first.body.refresh_token);
  assert.equal((await request('/api/v1/auth/me', undefined, refreshed.body.token)).status, 200);
  result.checks.access_expiry_refresh = 'PASS';
  await new Promise(resolve => setTimeout(resolve, 11500));
  assert.equal((await request('/api/v1/auth/refresh', { refresh_token: untouched.body.refresh_token })).status, 401);
  result.checks.refresh_expiry = 'PASS';
} catch (error) {
  result.checks.expiry = 'FAIL';
  writeFileSync(join(output, 'private-error.txt'), error.stack, { mode: 0o600 });
} finally {
  console.log('[a04] restore original token lifetimes');
  try {
    deploy(original.JWT_ACCESS_TTL, original.JWT_REFRESH_TTL);
    const restored = environment();
    assert.equal(restored.JWT_ACCESS_TTL, original.JWT_ACCESS_TTL);
    assert.equal(restored.JWT_REFRESH_TTL, original.JWT_REFRESH_TTL);
    result.checks.restored = 'PASS';
  } catch (error) {
    result.checks.restored = 'FAIL';
    writeFileSync(join(output, 'private-restore-error.txt'), error.stack, { mode: 0o600 });
  }
  result.status = Object.keys(result.checks).length === 3 && Object.values(result.checks).every(v => v === 'PASS') ? 'PASS' : 'FAIL';
  writeFileSync(join(output, 'result.json'), JSON.stringify(result, null, 2) + '\n');
}
console.log(`[a04] ${result.status}; ${output}`);
process.exitCode = result.status === 'PASS' ? 0 : 1;
