#!/usr/bin/env node
// A08 copied media access and instance-wide download revocation.
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
assert.ok(output, 'usage: media-access-smoke.mjs A03_OUTPUT A04_ACTORS MP4 PREPARED_FIXTURE NEW_OUTPUT');
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
let actor,owner,setting,passwordID,caption=false;
try{
 step('fixture-identity');
 for(const service of ['api','frontend']){
  const tag=service==='api'?'vidra-core:a08-source':'vidra-user:a08-source';
  assert.equal(guest(['docker','inspect','--format','{{.Image}}',`${a03.project}-${service}-1`]).trim(),prepared.images[tag]);
 }
 result.images=prepared.images;result.sources=prepared.sources;result.checks[phase]='PASS';
 actor=await login(actors.ordinary);owner=await login(actors.owner);
 const detail=await api(actor,`/api/v1/videos/${id}`);assert.equal(detail.status,200);assert.equal(detail.body.privacy,'public');assert.equal(detail.body.download_enabled,true);assert.equal(detail.body.has_storyboard,true);
 const settings=await api(owner,'/api/v1/admin/instance-settings');assert.equal(settings.status,200);setting=settings.body.settings.find(s=>s.key==='downloads_enabled');assert.ok(setting);assert.equal(setting.value,true);
 const ctx=await browser.newContext({baseURL:'https://secure.video.test',ignoreHTTPSErrors:true});const page=await ctx.newPage();await page.goto(`/v/${detail.body.short_code}`);
 step('instance-download-revocation');
 const listed=await api(actor,`/api/v1/videos/${id}/download`);assert.equal(listed.status,200);const paths=[...new Set(listed.body.files.flatMap(f=>[f.url,f.video_only_url].filter(Boolean)))];
 assert.equal((await api(owner,'/api/v1/admin/instance-settings','PATCH',{downloads_enabled:false})).status,200);
 result.global_downloads=await page.evaluate(async paths=>{const rows=[];for(const path of paths){const r=await fetch(path);rows.push({path,status:r.status,code:(await r.json()).error?.code});}return rows;},[`/api/v1/videos/${id}/download`,...paths]);
 for(const r of result.global_downloads){assert.equal(r.status,403);assert.equal(r.code,'feature_disabled');}
 result.global_streaming=await sample(page);
 assert.equal((await api(owner,'/api/v1/admin/instance-settings','PATCH',{downloads_enabled:setting.overridden?setting.value:null})).status,200);result.checks[phase]='PASS';checkpoint();
 step('media-assets');
 const captions=await api(actor,`/api/v1/videos/${id}/captions`);assert.equal(captions.status,200);assert.ok(!captions.body.captions.some(c=>c.language==='zxx'));
 const uploaded=await actor.page.evaluate(async({id,token})=>{const f=new FormData();f.set('language','zxx');f.set('label','A08 synthetic access test');f.set('file',new Blob(['WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nA08 access boundary\n'],{type:'text/vtt'}),'a08.vtt');return (await fetch(`/api/v1/videos/${id}/captions`,{method:'POST',headers:{Authorization:`Bearer ${token}`},body:f})).status;},{id,token:actor.token});assert.equal(uploaded,201);caption=true;
 // Walk the advertised tree, including alternate audio and init files; do not
 // assume one rendition or certify only a hardcoded first segment.
 const hlsPaths=await page.evaluate(async id=>{
  const prefix=`/api/v1/videos/${id}/`;const pending=[prefix+'hls/master.m3u8'];const seen=new Set();
  while(pending.length){
   const path=pending.shift();if(seen.has(path))continue;seen.add(path);
   if(!path.startsWith(prefix+'hls/')||seen.size>500)throw new Error('unexpected HLS tree');
   if(!path.endsWith('.m3u8'))continue;
   const r=await fetch(path);if(r.status!==200)throw new Error('manifest unavailable');
   const text=await r.text();const refs=[...text.matchAll(/URI="([^"]+)"/g)].map(m=>m[1]);
   refs.push(...text.split('\n').map(s=>s.trim()).filter(s=>s&&!s.startsWith('#')));
   for(const ref of refs){const u=new URL(ref,new URL(path,location.origin));if(u.origin!==location.origin)throw new Error('unexpected media origin');pending.push(u.pathname);}
  }
  return [...seen].map(p=>p.slice(prefix.length));
 },id);assert.ok(hlsPaths.some(p=>p.endsWith('.m4s')));assert.ok(hlsPaths.some(p=>p.endsWith('.mp4')));
 const suffixes=['original','thumbnail','storyboard.jpg','storyboard.vtt','captions','captions/zxx',...hlsPaths];
 result.asset_count=suffixes.length;
 const probe=(target)=>target.evaluate(async({id,suffixes})=>{const rows=[];for(const suffix of suffixes){const r=await fetch(`/api/v1/videos/${id}/${suffix}`,{cache:'no-store'});rows.push({suffix,status:r.status,bytes:(await r.arrayBuffer()).byteLength});}return rows;},{id,suffixes});
 result.public_assets=await probe(page);for(const r of result.public_assets){assert.equal(r.status,200);assert.ok(r.bytes>0);}
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'unlisted'})).status,200);result.unlisted_assets=await probe(page);checkpoint();for(const r of result.unlisted_assets)assert.equal(r.status,200);
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'private'})).status,200);result.private_owner_assets=await probe(actor.page);result.private_anonymous_assets=await probe(page);checkpoint();
 for(const r of result.private_owner_assets)assert.equal(r.status,200);for(const r of result.private_anonymous_assets)assert.equal(r.status,404);
 result.checks[phase]='PASS';checkpoint();

 step('password-media-assets');
 const passwords=await api(actor,`/api/v1/videos/${id}/passwords`);assert.equal(passwords.status,200);assert.equal(passwords.body.passwords.length,0);
 const password='A08-'+crypto.randomUUID();
 const added=await api(actor,`/api/v1/videos/${id}/passwords`,'POST',{password});assert.equal(added.status,201);passwordID=uuid(added.body.id);
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'password'})).status,200);
 await page.goto(`/v/${detail.body.short_code}`);
 await page.getByLabel('Video password',{exact:true}).fill(password);
 const pending=page.waitForResponse(r=>r.url().endsWith(`/api/v1/videos/${id}/unlock`)&&r.request().method()==='POST');
 await page.getByRole('button',{name:'Unlock',exact:true}).click();const unlocked=await pending;assert.equal(unlocked.status(),200);
 const playbackToken=(await unlocked.json()).playback_token;assert.ok(playbackToken);
 result.password_playback=await sample(page);
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

 result.password_assets=await page.evaluate(async({id,suffixes,playbackToken,expired})=>{
  const rows=[];for(const suffix of suffixes){
   const path=`/api/v1/videos/${id}/${suffix}`;const row={suffix};
   for(const [kind,token] of [['unlocked',playbackToken],['expired',expired],['bare',null]]){
    const r=await fetch(path+(token?'?pt='+encodeURIComponent(token):''),{cache:'no-store'});row[kind]=r.status;
   }rows.push(row);
  }return rows;
 },{id,suffixes,playbackToken,expired:tokens.expired});
 for(const r of result.password_assets){assert.equal(r.unlocked,200);assert.equal(r.expired,401);assert.equal(r.bare,401);}
 result.checks[phase]='PASS';
 result.status='PASS';
}catch(e){result.status='FAIL';result.checks[phase]='FAIL';writeFileSync(join(output,'private-error.txt'),e.stack,{mode:0o600});}
finally{
 if(actor)result.restore_privacy=(await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'}).catch(()=>null))?.status;
 if(passwordID)result.password_cleanup=(await api(actor,`/api/v1/videos/${id}/passwords/${passwordID}`,'DELETE').catch(()=>null))?.status;
 if(caption)result.caption_cleanup=(await api(actor,`/api/v1/videos/${id}/captions/zxx`,'DELETE').catch(()=>null))?.status;
 if(owner&&setting)result.restore_downloads=(await api(owner,'/api/v1/admin/instance-settings','PATCH',{downloads_enabled:setting.overridden?setting.value:null}).catch(()=>null))?.status;
 if(result.restore_privacy!==200||result.restore_downloads!==200||(caption&&result.caption_cleanup!==204)||(passwordID&&result.password_cleanup!==204))result.status='FAIL';
 await browser.close();checkpoint();
}
console.log(JSON.stringify({status:result.status,checks:result.checks,restore_privacy:result.restore_privacy,restore_downloads:result.restore_downloads,caption_cleanup:result.caption_cleanup}));process.exitCode=result.status==='PASS'?0:1;
