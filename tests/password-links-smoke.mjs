#!/usr/bin/env node
// A08 password watch/embed playback against the exact-source lab fixture.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateTarget } from './owner-auth-smoke.mjs';
assert.ok(Number(process.versions.node.split('.')[0]) >= 24, 'Node >=24 required');
const [a03dir, actorsDir, fixture, preparedDir, output] = process.argv.slice(2);
assert.ok(output, 'usage: links-smoke.mjs A03_OUTPUT A04_ACTORS MP4 PREPARED_FIXTURE NEW_OUTPUT');
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
let phase = 'setup';
const step = name => { phase = name; console.log(`[a08] ${name}`); };
const login = async actor => {
  const ctx = await browser.newContext({ baseURL: 'https://secure.video.test', ignoreHTTPSErrors: true, viewport: {width:1920,height:1080} });
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

const prepared=JSON.parse(readFileSync(join(preparedDir,'result.json')));
assert.equal(prepared.status,'PASS');assert.equal(prepared.project,a03.project);assert.equal(prepared.vm,vm);
const a06=JSON.parse(readFileSync('docs/evidence/a06-upload.json'));
assert.equal(a06.fixture_sha256,hash(bytes));const id=uuid(a06.video_id);
result.video_id=id;result.prepared_fixture_sha256=hash(readFileSync(join(preparedDir,'result.json')));
const checkpoint=()=>writeFileSync(join(output,'result.json'),JSON.stringify(result,null,2)+'\n');
const sample=async page=>{
 const video=page.locator('video:visible').first();await expect(video).toBeVisible();
 await page.waitForLoadState('networkidle');
 await expect(async()=>assert.ok(await video.evaluate(v=>v.readyState>=2))).toPass({timeout:30000});
 await video.evaluate(v=>Promise.race([v.play(),new Promise((_,reject)=>setTimeout(()=>reject(new Error('play stalled')),10000))]));
 let measurement;
 await expect(async()=>{
   measurement=await video.evaluate(v=>({time:v.currentTime,frames:v.getVideoPlaybackQuality().totalVideoFrames,src:v.currentSrc.split('?')[0],audio:v.webkitAudioDecodedByteCount}));
   assert.ok(measurement.time>2);assert.ok(measurement.frames>0);assert.ok(measurement.audio>0);
 }).toPass({timeout:15000});await video.evaluate(v=>v.pause());return measurement;
};
let actor;let passwordID;
try {
 step('fixture-identity');
 for(const service of ['api','frontend']){
  const tag=service==='api'?'vidra-core:a08-source':'vidra-user:a08-source';
  assert.equal(guest(['docker','inspect','--format','{{.Image}}',`${a03.project}-${service}-1`]).trim(),prepared.images[tag]);
 }
 result.checks[phase]='PASS';
 actor=await login(actors.ordinary);
 const code=sql(`SELECT short_code FROM videos WHERE id='${id}'`);result.short_code=code;
 assert.equal((await api(actor,`/api/v1/videos/${id}`)).body.privacy,'public');
 const listed=await api(actor,`/api/v1/videos/${id}/passwords`);assert.equal(listed.status,200);assert.equal(listed.body.passwords.length,0);
 const password='A08-'+crypto.randomUUID();
 const added=await api(actor,`/api/v1/videos/${id}/passwords`,'POST',{password});assert.equal(added.status,201);passwordID=uuid(added.body.id);
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'password'})).status,200);
 const context=await browser.newContext({baseURL:'https://secure.video.test',ignoreHTTPSErrors:true});const page=await context.newPage();
 for(const path of [`/v/${code}`,`/embed/${id}`]){
  step(path.startsWith('/embed')?'password-embed':'password-watch');
  await page.goto(path);await expect(page.getByLabel('Video password',{exact:true})).toBeVisible();
  await page.getByLabel('Video password',{exact:true}).fill('wrong-password');await page.getByRole('button',{name:'Unlock',exact:true}).click();
  await expect(page.getByText('That password is incorrect.',{exact:true})).toBeVisible();
  await page.getByLabel('Video password',{exact:true}).fill(password);
  const pending=page.waitForResponse(r=>r.url().endsWith(`/api/v1/videos/${id}/unlock`)&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Unlock',exact:true}).click();const unlocked=await pending;assert.equal(unlocked.status(),200);
  const token=(await unlocked.json()).playback_token;assert.ok(token);
  result[phase]={playback:await sample(page)};
  result[phase].assets=await page.evaluate(async({id,token})=>{
    const outcomes=[];for(const suffix of ['original','thumbnail','hls/master.m3u8']){
     const path=`/api/v1/videos/${id}/${suffix}`;
     const allowed=await fetch(path+'?pt='+encodeURIComponent(token));const denied=await fetch(path);
     outcomes.push({suffix,unlocked:allowed.status,bare:denied.status});
    }return outcomes;
  },{id,token});
  for(const asset of result[phase].assets){assert.equal(asset.unlocked,200);assert.equal(asset.bare,401);}
  result.checks[phase]='PASS';checkpoint();
  await new Promise(resolve=>setTimeout(resolve,30000));
 }
 step('playback-token-expiry');
 // Sign a valid/expired control pair inside the disposable guest. The signing
 // secret never leaves it; tokens stay in memory and are absent from evidence.
 const tokens=JSON.parse(guest(['python3','-c',`
import base64,hashlib,hmac,json,subprocess,sys,time,uuid
config=json.loads(subprocess.check_output(['docker','inspect',sys.argv[1]+'-api-1']))[0]
env=dict(v.split('=',1) for v in config['Config']['Env'] if '=' in v)
key=hmac.new(env['JWT_SECRET'].encode(),b'vidra/playback-token/v1',hashlib.sha256).digest()
def encode(b): return base64.urlsafe_b64encode(b).decode().rstrip('=')
def token(exp):
 payload=('v2:'+sys.argv[2]+':'+str(uuid.uuid4())+':playback:'+str(exp)).encode()
 return encode(payload)+'.'+encode(hmac.new(key,payload,hashlib.sha256).digest())
now=int(time.time())
print(json.dumps({'valid':token(now+300),'expired':token(now-60)}))
`,a03.project,id]));
 result.expiry=await page.evaluate(async({id,tokens})=>{
   const url=(path,token)=>{const u=new URL(path,location.origin);u.searchParams.set('pt',token);return u.href;};
   const master=`/api/v1/videos/${id}/hls/master.m3u8`;
   const firstURI=text=>text.split('\n').map(s=>s.trim()).find(s=>s&&!s.startsWith('#'));
   const masterResponse=await fetch(url(master,tokens.valid));if(masterResponse.status!==200)throw new Error('valid master control failed');
   const variant=new URL(firstURI(await masterResponse.text()),new URL(master,location.origin));
   const variantResponse=await fetch(url(variant.pathname,tokens.valid));if(variantResponse.status!==200)throw new Error('valid variant control failed');
   const segment=new URL(firstURI(await variantResponse.text()),variant);
   if(!variant.pathname.startsWith(`/api/v1/videos/${id}/hls/`)||!segment.pathname.startsWith(`/api/v1/videos/${id}/hls/`))throw new Error('unexpected HLS asset path');
   const outcomes=[];
   for(const path of [`/api/v1/videos/${id}/original`,`/api/v1/videos/${id}/thumbnail`,master,variant.pathname,segment.pathname]){
    const valid=await fetch(url(path,tokens.valid)),expired=await fetch(url(path,tokens.expired));
    outcomes.push({path,valid:valid.status,expired:expired.status});
   }
   return outcomes;
 },{id,tokens});
 for(const asset of result.expiry){assert.equal(asset.valid,200);assert.equal(asset.expired,401);}
 result.checks[phase]='PASS';
 result.status='PASS';
}catch(error){result.status='FAIL';result.checks[phase]='FAIL';writeFileSync(join(output,'private-error.txt'),error.stack,{mode:0o600});}
finally{
 if(actor){
  const restore=await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'}).catch(()=>null);result.restore_status=restore?.status;
  if(passwordID&&restore?.status===200)result.password_delete_status=(await api(actor,`/api/v1/videos/${id}/passwords/${passwordID}`,'DELETE')).status;
  if(result.restore_status!==200||result.password_delete_status!==204)result.status='FAIL';
 }
 await browser.close();checkpoint();
}
console.log(JSON.stringify({status:result.status,checks:result.checks,restore:result.restore_status,password_delete:result.password_delete_status}));process.exitCode=result.status==='PASS'?0:1;
