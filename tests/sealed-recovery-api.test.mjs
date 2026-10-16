import assert from 'node:assert/strict';
import { chmodSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { fixtureClient, totp } from './sealed-recovery-api.mjs';

// Public RFC6238 Appendix B SHA1 ASCII seed, not an operational credential:
// https://www.rfc-editor.org/rfc/rfc6238#appendix-B
const rfcBits = [...Buffer.from('12345678901234567890', 'ascii')].map(byte => byte.toString(2).padStart(8, '0')).join('');
const SECRET = rfcBits.match(/.{5}/g).map(bits => 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'[Number.parseInt(bits, 2)]).join('');
const BASE = 'http://127.0.0.1:8080';
async function fixture(run) {
  const dir = mkdtempSync(join(tmpdir(), 'sealed-api-')); const file = join(dir, 'fixture.json');
  let clock = 1800000000000, wrongKey = false, bypass = false, acceptWrong = false, rateLimit = 0;
  let issued = 0, invalidAfter = Infinity, retryAfter = 31;
  const requests = []; let mail, provider;
  const fetchImpl = async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : undefined; requests.push({ url, ...options, body });
    let status = 200, result;
    if (url.endsWith('/setup/claim-owner')) { status = 201; result = { token: 'a.b.c' }; }
    else if (url.endsWith('/auth/mfa/totp')) result = { secret: SECRET };
    else if (url.endsWith('/auth/mfa/totp/verify')) result = { recovery_codes: ['private-recovery-canary'] };
    else if (url.endsWith('/auth/login')) { issued = clock; result = bypass ? { token: 'a.b.c' } : { mfa_required: true, mfa_token: 'challenge' }; }
    else if (url.endsWith('/auth/mfa/challenge')) {
      if (rateLimit) { rateLimit--; status = 429; }
      else if (clock - issued >= invalidAfter) { status = 401; result = { error: { code: 'unauthorized', message: 'invalid or expired mfa token' } }; }
      else if (acceptWrong || (!wrongKey && body.code === totp(SECRET, clock))) result = { token: 'a.b.c' };
      else { status = 401; result = { error: { code: 'unauthorized', message: 'invalid code', request_id: 'private-body-canary' } }; }
    } else if (url.endsWith('/admin/mail-config')) {
      if (options.method === 'PUT') mail = { source: 'database', secrets_available: true, secret_status: 'ok', config: { transport: 'smtp', from_address: body.from_address,
        smtp: { host: body.smtp.host, port: body.smtp.port, username: body.smtp.username, encryption: body.smtp.encryption, password_set: true } } };
      result = { ...mail, secret_status: wrongKey ? 'undecryptable' : 'ok' };
    } else if (url.endsWith('/admin/oidc-providers')) {
      if (options.method === 'POST') { status = 201; provider = { name: body.name, enabled: body.enabled, client_id: body.client_id, issuer_url: body.issuer_url,
        auto_provision: body.auto_provision, secret_configured: true, secret_status: 'ok' }; }
      result = options.method === 'POST' ? provider : { secrets_available: true, providers: [{ ...provider, secret_status: wrongKey ? 'undecryptable' : 'ok' }] };
    } else assert.fail('unexpected endpoint');
    return { status, headers: new Headers({ 'retry-after': String(retryAfter) }), json: async () => result };
  };
  const client = fixtureClient({ baseUrl: BASE, fetchImpl, now: () => clock, sleep: async ms => { clock += ms; } });
  try { await run({ client, file, dir, requests, setWrongKey: () => { wrongKey = true; },
    bypass: () => { bypass = true; }, acceptWrong: () => { acceptWrong = true; }, rateLimit: () => { rateLimit = 1; },
    expireChallenge: retries => { wrongKey = true; acceptWrong = true; invalidAfter = retries ? 300000 : 0; rateLimit = retries; retryAfter = 120; } }); }
  finally { rmSync(dir, { recursive: true }); }
}

test('RFC6238 vector uses SHA1, 30-second counter and six digits', () => assert.equal(totp(SECRET, 59000), '287082'));
test('source creates only synthetic private state and safe disabled provider fixtures', () => fixture(async ({ client, file, requests }) => {
  const verdict = await client('source', file, 'setup_token_canary_123456');
  const state = JSON.parse(readFileSync(file));
  assert.equal(verdict.status, 'PASS'); assert.equal(state.email, 'synthetic-recovery@recovery.invalid');
  assert.equal(Object.keys(state).sort().join(), 'email,last_step,mfa_secret,password,synthetic_only,token');
  const smtp = requests.find(r => r.method === 'PUT').body.smtp;
  assert.deepEqual({ ...smtp, password: 'redacted' }, { host: '127.0.0.1', port: 1, username: 'ci', encryption: 'none', password: 'redacted' });
  const oidc = requests.find(r => r.url.endsWith('/oidc-providers') && r.method === 'POST').body;
  assert.equal(oidc.enabled, false); assert.equal(oidc.auto_provision, false);
  assert.equal(oidc.issuer_url, 'https://oidc.example.com');
  for (const secret of [state.password, SECRET, smtp.password, oidc.client_secret, 'private-recovery-canary']) {
    assert.ok(!JSON.stringify(verdict).includes(secret));
    if (![state.password, SECRET].includes(secret)) assert.ok(!readFileSync(file, 'utf8').includes(secret));
  }
  assert.ok(requests.every(r => r.url.startsWith(`${BASE}/api/v1/`) && r.redirect === 'error'));
}));
test('restore verifies wrong TOTP then fresh good TOTP, and wrong KEK fails all three secrets', () => fixture(async f => {
  await f.client('source', f.file, 'setup_token_canary_123456');
  const before = JSON.parse(readFileSync(f.file)).last_step;
  f.rateLimit(); const restored = await f.client('verify', f.file);
  assert.equal(restored.mfa_wrong_code_refused, true); assert.equal(restored.mfa_correct_code_accepted, true);
  assert.ok(JSON.parse(readFileSync(f.file)).last_step > before);
  f.setWrongKey(); assert.equal((await f.client('wrong-key', f.file)).wrong_key_refused, true);
}));
test('an MFA bypass and an accepted wrong TOTP cannot pass restore', async () => {
  for (const change of ['bypass', 'acceptWrong']) await fixture(async f => {
    await f.client('source', f.file, 'setup_token_canary_123456'); f[change]();
    await assert.rejects(f.client('verify', f.file), /mfa_required|wrong_totp/);
  });
});
test('wrong-key control cannot pass while stored secrets still decrypt', () => fixture(async f => {
  await f.client('source', f.file, 'setup_token_canary_123456');
  await assert.rejects(f.client('wrong-key', f.file), /mail_secret/);
}));
test('wrong-key control also requires MFA rejection', () => fixture(async f => {
  await f.client('source', f.file, 'setup_token_canary_123456'); f.setWrongKey(); f.acceptWrong();
  await assert.rejects(f.client('wrong-key', f.file), /wrong_key_mfa/);
}));
test('invalid or expired MFA challenges cannot prove wrong-key refusal', async () => {
  for (const retries of [0, 3]) await fixture(async f => {
    await f.client('source', f.file, 'setup_token_canary_123456');
    const state = readFileSync(f.file); f.expireChallenge(retries);
    await assert.rejects(f.client('wrong-key', f.file), /wrong_key_mfa/);
    assert.ok(readFileSync(f.file).equals(state), 'failure must not rewrite private state');
  });
});
test('raw HTTP, JSON and network failures never promote private payloads into errors', () => fixture(async f => {
  for (const [fetchImpl, expected] of [
    [async () => ({ status: 500, json: async () => ({ message: 'private-canary' }) }), 'owner_claim'],
    [async () => ({ status: 200, json: async () => { throw new Error('private-canary'); } }), 'response_json'],
    [async () => { throw new Error('private-canary'); }, 'request_failed'],
  ]) await assert.rejects(fixtureClient({ baseUrl: BASE, fetchImpl })('source', f.file, 'setup_token_canary_123456'),
    error => error.message === expected && !error.stack.includes('private-canary'));
}));
test('public state permissions and non-loopback targets fail before HTTP', () => fixture(async f => {
  await f.client('source', f.file, 'setup_token_canary_123456'); const calls = f.requests.length;
  await assert.rejects(f.client('source', f.file, 'setup_token_canary_123456'), /private_state/);
  chmodSync(f.file, 0o644); await assert.rejects(f.client('verify', f.file), /private_state/);
  assert.equal(f.requests.length, calls);
  assert.throws(() => fixtureClient({ baseUrl: 'https://private-canary.example' }), /loopback_origin/);
}));
test('CLI errors contain only fixed codes and never echo credential input', () => {
  const run = spawnSync(process.execPath, [new URL('./sealed-recovery-api.mjs', import.meta.url).pathname, 'source', '/private-canary'],
    { encoding: 'utf8', env: { PATH: process.env.PATH, VIDRA_BASE_URL: 'https://private-canary.example', VIDRA_SETUP_TOKEN: 'private-canary' } });
  assert.equal(run.status, 1); assert.equal(run.stderr, ''); assert.ok(!run.stdout.includes('private-canary'));
  assert.deepEqual(JSON.parse(run.stdout), { status: 'FAIL', phase: 'source', error: 'loopback_origin' });
});
