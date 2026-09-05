#!/usr/bin/env node
// A08 link and private-media reproduction against the exact-source lab fixture.
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
let actor;
const privateResponses=[];
try{
 step('fixture-identity');
 for(const service of ['api','frontend']){
   const tag=service==='api'?'vidra-core:a08-source':'vidra-user:a08-source';
   assert.equal(guest(['docker','inspect','--format','{{.Image}}',`${a03.project}-${service}-1`]).trim(),prepared.images[tag]);
 }
 const code=sql(`SELECT short_code FROM videos WHERE id='${id}'`);assert.match(code,/^[1-9A-HJ-NP-Za-km-z]{11}$/);result.short_code=code;
 actor=await login(actors.ordinary);const detail=await api(actor,`/api/v1/videos/${id}`);assert.equal(detail.status,200);
 const title=detail.body.title;assert.equal(detail.body.short_code,code);
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'})).status,200);
 result.checks[phase]='PASS';checkpoint();
 step('canonical-legacy-timestamps');
 const alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';let number=BigInt('0x'+id.replaceAll('-','')),sid='';
 while(number){sid=alphabet[Number(number%58n)]+sid;number/=58n;}
 const zeroBytes=id.replaceAll('-','').match(/^(00)*/)[0].length/2;sid='1'.repeat(zeroBytes)+sid;
 const flickr='123456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ';
 const peerTubeSID=[...sid].map(c=>flickr[alphabet.indexOf(c)]).join('').padStart(22,'1');
 const context=await browser.newContext({baseURL:'https://secure.video.test',ignoreHTTPSErrors:true,viewport:{width:1600,height:1000}});
 const page=await context.newPage();result.links=[];
 for(const path of [`/v/${code}`,`/videos/${id}`,`/v/${sid}`,`/w/${peerTubeSID}`,`/videos/watch/${id}`]){
   result.active_path=path;checkpoint();const response=await page.goto(path+'?t=2');assert.equal(response.status(),200);
   await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();
   const canonical=await page.locator('link[rel="canonical"]').getAttribute('href');assert.equal(canonical,`https://secure.video.test/v/${code}`);
   const playback=await sample(page);assert.ok(playback.time>=2);
   result.links.push({path,final_url:page.url(),canonical,playback});checkpoint();
   // Each navigation boots the full app; pace the rehearsal within API limits.
   await new Promise(resolve=>setTimeout(resolve,10000));
 }
 result.checks[phase]='PASS';checkpoint();
 step('share-embed-link');
 await page.locator('#main-content').getByRole('button',{name:'Share',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Share this video'});await expect(dialog).toBeVisible();
 await dialog.getByRole('checkbox',{name:/Start at/}).check();
 const shareURL=await dialog.getByLabel('Watch page link',{exact:true}).inputValue();const embed=await dialog.getByLabel('Embed code',{exact:true}).inputValue();
 assert.equal(new URL(shareURL).pathname,`/v/${code}`);assert.ok(new URL(shareURL).searchParams.has('t'));
 const embedURL=embed.match(/src="([^"]+)"/)[1].replaceAll('&amp;','&');result.share={url:shareURL,embed_url:embedURL};
 await page.goto(embedURL);await expect(page.getByRole('link',{name:title,exact:true})).toBeVisible();result.embed_playback=await sample(page);
 await expect(page.getByRole('link',{name:'Home',exact:true})).toHaveCount(0);
 result.checks[phase]='PASS';checkpoint();
 step('private-owner-and-anonymous-media');
 actor.page.on('response',r=>{if(r.url().includes('/api/v1/'))privateResponses.push({path:new URL(r.url()).pathname,status:r.status(),bearer:!!r.request().headers().authorization});});
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'private'})).status,200);
 result.private_media=await actor.page.evaluate(async({id,token})=>{
   const outcomes=[];for(const suffix of ['original','thumbnail','hls/master.m3u8']){
     const url=`/api/v1/videos/${id}/${suffix}`;
     const authed=await fetch(url,{headers:{Authorization:`Bearer ${token}`}});const plain=await fetch(url);
     outcomes.push({suffix,authenticated:authed.status,owner_native:plain.status});
   }return outcomes;
 },{id,token:actor.token});
 for(const outcome of result.private_media){
   outcome.anonymous=await page.evaluate(async({id,suffix})=>(await fetch(`/api/v1/videos/${id}/${suffix}`)).status,{id,suffix:outcome.suffix});
   assert.equal(outcome.authenticated,200);assert.equal(outcome.anonymous,404);
 }
 checkpoint();await actor.page.goto(`/v/${code}`);await expect(actor.page.getByRole('heading',{name:title,exact:true})).toBeVisible();
 result.private_playback=await sample(actor.page);
 result.checks[phase]='PASS';
 // These phases are a reproduction slice; broader A08 stays open until its
 // password/expiry/download and embed-origin/legacy-import acceptance runs.
 result.status='PASS';
}catch(error){
 result.checks[phase]='FAIL';result.status='FAIL';
 writeFileSync(join(output,'private-error.txt'),error.stack,{mode:0o600});
 if(actor)await actor.page.screenshot({path:join(output,'private-failure.png'),fullPage:true}).catch(()=>{});
}
finally{
 result.private_responses=privateResponses;
 if(actor){
   let restored=await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'}).catch(()=>null);
   // Navigation may replace the page's execution context, and long media runs
   // can outlive the captured bearer. Restore with a fresh login if needed.
   if(restored?.status!==200){
     const recovery=await login(actors.ordinary).catch(()=>null);
     if(recovery)restored=await api(recovery,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'}).catch(()=>null);
   }
   for(let attempt=0;restored?.status===429&&attempt<3;attempt++){
     await actor.page.goto('about:blank');
     await new Promise(resolve=>setTimeout(resolve,30000));
     const recovery=await login(actors.ordinary).catch(()=>null);
     if(recovery)restored=await api(recovery,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'}).catch(()=>null);
   }
   result.restore_status=restored?.status??null;result.restored_public=restored?.status===200;
   if(!result.restored_public)result.status='FAIL';
 }
 await browser.close();checkpoint();
}
console.log(`[a08] ${result.status}; ${output}`);process.exitCode=result.status==='PASS'?0:1;
