// Synthetic isolated fixture only. Private state is never returned or logged.
import { createHmac, randomBytes } from 'node:crypto';
import { lstatSync, readFileSync, realpathSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const EMAIL = 'synthetic-recovery@recovery.invalid';
const NAME = 'synthetic-recovery';
class Failure extends Error {}
const check = (ok, code) => { if (!ok) throw new Failure(code); };
// Core deliberately shares this refusal for bad TOTP and undecryptable secrets;
// an invalid/expired challenge is a different 401 and proves neither condition.
const codeRefused = ({ status, body }) => status === 401 && body?.error?.code === 'unauthorized' &&
  body.error.message === 'invalid code' && !body.token && !body.refresh_token;
export function totp(secret, now) {
  check(typeof secret === 'string' && /^[A-Z2-7]{16,128}={0,6}$/.test(secret), 'totp_secret');
  let bits = 0, value = 0; const bytes = [];
  for (const char of secret.replace(/=+$/, '')) {
    value = (value << 5) | 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'.indexOf(char); bits += 5;
    if (bits >= 8) { bits -= 8; bytes.push((value >>> bits) & 255); }
  }
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(now / 30000)));
  const hash = createHmac('sha1', Buffer.from(bytes)).update(counter).digest();
  return String((hash.readUInt32BE(hash[19] & 15) & 0x7fffffff) % 1000000).padStart(6, '0');
}

function statePath(file, source) {
  check(typeof file === 'string' && resolve(file) === file, 'state_path');
  const parent = lstatSync(dirname(file));
  check(parent.isDirectory() && realpathSync(dirname(file)) === dirname(file) &&
    parent.uid === process.getuid() && (parent.mode & 0o777) === 0o700, 'private_directory');
  const stat = lstatSync(file, { throwIfNoEntry: false });
  check(source ? !stat : stat?.isFile() && stat.uid === process.getuid() && (stat.mode & 0o777) === 0o600, 'private_state');
}
function readState(file) {
  const state = JSON.parse(readFileSync(file, 'utf8'));
  check(Object.keys(state).sort().join() === 'email,last_step,mfa_secret,password,synthetic_only,token', 'state_fields');
  check(state.synthetic_only === true && state.email === EMAIL && /^[a-f0-9]{64}$/.test(state.password) &&
    Number.isSafeInteger(state.last_step) && state.last_step >= 0 && typeof state.token === 'string' &&
    /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(state.token), 'state_fixture');
  totp(state.mfa_secret, 0); return state;
}
function saveState(file, state, source) {
  if (source) writeFileSync(file, JSON.stringify(state), { flag: 'wx', mode: 0o600 });
  else { writeFileSync(`${file}.new`, JSON.stringify(state), { flag: 'wx', mode: 0o600 }); renameSync(`${file}.new`, file); }
}

export function fixtureClient({ baseUrl, internalOrigin, fetchImpl = fetch, now = Date.now,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)) }) {
  // The host verifies Docker ownership and subnet membership before supplying a
  // private bridge address. Literal matching rejects credentials, whitespace
  // and alternate IPv4 spellings before URL parsing can normalize the input.
  const origin = typeof baseUrl === 'string' && /^http:\/\/((?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}):8080$/.exec(baseUrl);
  const ip = origin ? origin[1].split('.').map(Number) : [];
  check(baseUrl === 'http://127.0.0.1:8080' || (internalOrigin === baseUrl && origin && origin[0] === baseUrl && ip.every(octet => octet <= 255) &&
    (ip[0] === 10 || (ip[0] === 172 && ip[1] >= 16 && ip[1] <= 31) || (ip[0] === 192 && ip[1] === 168))), 'loopback_origin');
  const request = async (path, method = 'GET', body, token) => {
    for (let attempt = 0; attempt < 5; attempt++) {
      let response;
      try {
        // Waiting for an unused TOTP window precedes the network deadline.
        const payload = body ? JSON.stringify(typeof body === 'function' ? await body() : body) : undefined;
        response = await fetchImpl(`${baseUrl}/api/v1${path}`, { method, redirect: 'error', signal: AbortSignal.timeout(15000),
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: payload });
      } catch { throw new Failure('request_failed'); }
      if (response.status === 429) {
        const delay = Number(response.headers.get('retry-after'));
        check(Number.isFinite(delay) && delay >= 0 && delay <= 120, 'rate_limit');
        await sleep((delay || 30) * 1000 + 1000); continue;
      }
      try { return { status: response.status, body: await response.json() }; }
      catch { throw new Failure('response_json'); }
    }
    throw new Failure('rate_limit');
  };
  const freshCode = async state => {
    for (let tries = 0; tries < 90; tries++) {
      const time = now(), step = Math.floor(time / 30000);
      if (step > state.last_step && time % 30000 <= 25000) return { code: totp(state.mfa_secret, time), step };
      await sleep(1000);
    }
    throw new Failure('totp_clock');
  };
  const login = async (state, wrongFirst = false, wrongKey = false) => {
    const challenge = await request('/auth/login', 'POST', { identifier: EMAIL, password: state.password });
    check(challenge.status === 200 && challenge.body.mfa_required === true && typeof challenge.body.mfa_token === 'string' && !challenge.body.token && !challenge.body.refresh_token, 'mfa_required');
    const payload = async wrong => {
      const fresh = await freshCode(state);
      if (!wrong) return { mfa_token: challenge.body.mfa_token, code: fresh.code };
      const nearby = new Set([-30000, 0, 30000].map(offset => totp(state.mfa_secret, now() + offset)));
      let bad = 0; while (nearby.has(String(bad).padStart(6, '0'))) bad++;
      return { mfa_token: challenge.body.mfa_token, code: String(bad).padStart(6, '0') };
    };
    if (wrongFirst) { const refused = await request('/auth/mfa/challenge', 'POST', () => payload(true));
      check(codeRefused(refused), 'wrong_totp'); }
    let acceptedStep;
    const result = await request('/auth/mfa/challenge', 'POST', async () => {
      const fresh = await freshCode(state); acceptedStep = fresh.step;
      return { mfa_token: challenge.body.mfa_token, code: fresh.code };
    });
    if (wrongKey) { check(codeRefused(result), 'wrong_key_mfa'); return; }
    check(result.status === 200 && result.body.token, 'correct_totp');
    state.last_step = acceptedStep; state.token = result.body.token;
  };
  const settings = async (state, expected) => {
    const mail = await request('/admin/mail-config', 'GET', null, state.token);
    check(mail.status === 200 && mail.body.source === 'database' && mail.body.secrets_available === true && mail.body.secret_status === expected &&
      mail.body.config?.transport === 'smtp' && mail.body.config.smtp.host === '127.0.0.1' &&
      mail.body.config.smtp.port === 1 && mail.body.config.smtp.username === 'ci' && mail.body.config.smtp.encryption === 'none' &&
      mail.body.config.from_address === EMAIL && mail.body.config.smtp.password_set === true, 'mail_secret');
    const oidc = await request('/admin/oidc-providers', 'GET', null, state.token);
    const provider = oidc.body.providers?.[0];
    check(oidc.status === 200 && oidc.body.secrets_available === true && oidc.body.providers.length === 1 && provider.name === NAME &&
      provider.client_id === NAME && provider.issuer_url === 'https://oidc.example.com' &&
      provider.enabled === false && provider.auto_provision === false && provider.secret_configured === true &&
      provider.secret_status === expected, 'oidc_secret');
  };
  return async (mode, file, setupToken) => {
    check(['source', 'verify', 'wrong-key'].includes(mode), 'mode'); statePath(file, mode === 'source');
    const source = mode === 'source';
    const state = source ? { synthetic_only: true, email: EMAIL, password: randomBytes(32).toString('hex'), last_step: -1 } : readState(file);
    if (source) {
      check(typeof setupToken === 'string' && /^[A-Za-z0-9_-]{16,256}$/.test(setupToken), 'setup_token');
      const owner = await request('/setup/claim-owner', 'POST', { token: setupToken, username: NAME, email: EMAIL, password: state.password });
      check(owner.status === 201 && owner.body.token, 'owner_claim'); state.token = owner.body.token;
      const begin = await request('/auth/mfa/totp', 'POST', {}, state.token);
      check(begin.status === 200, 'mfa_enroll'); state.mfa_secret = begin.body.secret;
      let step;
      const enabled = await request('/auth/mfa/totp/verify', 'POST', async () => {
        const fresh = await freshCode(state); step = fresh.step; return { code: fresh.code };
      }, state.token);
      check(enabled.status === 200, 'mfa_enable'); state.last_step = step;
      await login(state);
      const mail = await request('/admin/mail-config', 'PUT', { current_password: state.password, transport: 'smtp',
        from_address: EMAIL, smtp: { host: '127.0.0.1', port: 1, username: 'ci', encryption: 'none', password: randomBytes(32).toString('hex') } }, state.token);
      check(mail.status === 200, 'mail_save');
      const oidc = await request('/admin/oidc-providers', 'POST', { current_password: state.password, name: NAME,
        display_name: 'Synthetic recovery', issuer_url: 'https://oidc.example.com', client_id: NAME, scopes: ['openid'],
        enabled: false, auto_provision: false, allowed_email_domains: [], client_secret: randomBytes(32).toString('hex') }, state.token);
      check(oidc.status === 201, 'oidc_save'); await settings(state, 'ok');
    } else if (mode === 'verify') { await login(state, true); await settings(state, 'ok'); }
    else { await settings(state, 'undecryptable'); await login(state, false, true); }
    saveState(file, state, source);
    return { status: 'PASS', synthetic_only: true, ...(mode === 'wrong-key' ? { wrong_key_refused: true } :
      { mfa_correct_code_accepted: true, mail_secret_status: 'ok', oidc_secret_status: 'ok', oidc_disabled: true,
        ...(mode === 'verify' ? { mfa_wrong_code_refused: true } : {}) }) };
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [mode, file] = process.argv.slice(2);
  try { console.log(JSON.stringify(await fixtureClient({ baseUrl: process.env.VIDRA_BASE_URL,
    internalOrigin: process.env.VIDRA_INTERNAL_ORIGIN })(mode, file, process.env.VIDRA_SETUP_TOKEN))); }
  catch (error) {
    console.log(JSON.stringify({ status: 'FAIL', phase: ['source', 'verify', 'wrong-key'].includes(mode) ? mode : 'input',
      error: error instanceof Failure ? error.message : 'internal' })); process.exitCode = 1;
  }
}
