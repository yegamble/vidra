#!/usr/bin/env node
// A07 exercises real HLS and progressive playback on the retained disposable stack.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateTarget } from './owner-auth-smoke.mjs';
assert.ok(Number(process.versions.node.split('.')[0]) >= 24, 'Node >=24 required');
const [a03dir, actorsDir, fixture, output] = process.argv.slice(2);
assert.ok(output, 'usage: playback-smoke.mjs A03_OUTPUT A04_ACTORS MP4 NEW_OUTPUT');
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
const step = name => { phase = name; console.log(`[a07] ${name}`); };
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

const a06 = JSON.parse(readFileSync('docs/evidence/a06-upload.json'));
assert.equal(a06.fixture_sha256,hash(bytes));
assert.equal(a06.vm, vm); assert.equal(a06.project, a03.project); assert.equal(a06.status, 'PASS');
const id = uuid(a06.video_id);
result.video_id = id;
const checkpoint = () => writeFileSync(join(output, 'result.json'), JSON.stringify(result, null, 2) + '\n');
const jobSnapshot = () => JSON.parse(sql(`SELECT row_to_json(j) FROM (SELECT id,state,attempts,next_attempt_at,updated_at FROM transcode_jobs WHERE video_id='${id}' ORDER BY created_at DESC LIMIT 1) j`));
const measurePlayback = async (page, source = 'blob:') => {
  await page.waitForLoadState('networkidle');
  const player = page.locator('#main-content').getByTestId('video-player').first();
  const video = player.locator('video'); await expect(video).toBeVisible();
  // Visibility precedes the async playback-session/engine attachment. Starting
  // before media is ready races its initial source reset and can lose the click.
  await expect(async()=>{
    result.ready_sample=await video.evaluate(v=>({ready:v.readyState,duration:v.duration,attribute:v.getAttribute('src')?.split('?')[0],src:v.currentSrc.split('?')[0],error:v.error?.message}));checkpoint();
    assert.ok(result.ready_sample.ready>=2 && result.ready_sample.duration>=4.9);
    assert.ok(source==='blob:' ? result.ready_sample.src.startsWith(source) : result.ready_sample.src.endsWith(source));
  }).toPass({timeout:60000});
  await video.evaluate(v => {v.pause();v.currentTime=0;v.muted=false;v.volume=1;});
  // Measure the production engine through the media API; UI-control behavior
  // has separate A40 acceptance and must not be inferred from this decode proof.
  await video.evaluate(v=>Promise.race([v.play(),new Promise((_,reject)=>setTimeout(()=>reject(new Error('play did not resolve')),15000))]));
  await expect(async () => {
    const sample=await video.evaluate(v=>{
      return {time:v.currentTime,muted:v.muted,paused:v.paused,ended:v.ended,ready:v.readyState,error:v.error?.message,width:v.videoWidth,height:v.videoHeight,frames:v.getVideoPlaybackQuality().totalVideoFrames,
        audio_decoded_bytes:v.webkitAudioDecodedByteCount ?? 0,src:v.currentSrc.split('?')[0]};
    });
    result.last_sample=sample;checkpoint();

    assert.equal(sample.muted,false);assert.ok(sample.time>1.5);assert.ok(sample.frames>0);assert.equal(sample.width,320);assert.equal(sample.height,240);assert.ok(sample.audio_decoded_bytes>0);
    result.last_playback=sample;
  }).toPass({timeout:60000,intervals:[100,250]});
  await video.evaluate(v=>{v.pause();v.currentTime=3.5;});
  await expect(async()=>{
    const seek=await video.evaluate(v=>({time:v.currentTime,seeking:v.seeking,ready:v.readyState}));
    assert.ok(Math.abs(seek.time-3.5)<0.3);assert.equal(seek.seeking,false);assert.ok(seek.ready>=2);
  }).toPass({timeout:15000});
  return {...result.last_playback,seek:await video.evaluate(v=>v.currentTime)};
};
try {
 const actor=await login(actors.ordinary); const page=actor.page;
 result.media_requests=[];
 page.on('response',async response=>{
   const url=new URL(response.url());
   if(!url.pathname.startsWith(`/api/v1/videos/${id}`))return;
   const entry={path:url.pathname,status:response.status()};
   result.media_requests.push(entry);
   if(url.pathname.endsWith('/playback-session')){
     const session=await response.json().catch(()=>null);
     entry.hls_advertised=Boolean(session?.hls_url);
   }
 });
 step('media-visibility-probe');
 result.probed_privacy=(await api(actor,`/api/v1/videos/${id}`)).body.privacy;
 result.thumbnail_probe=await page.evaluate(async({id,token})=>{
   const path=`/api/v1/videos/${id}/thumbnail`;
   const plain=await fetch(path);const authed=await fetch(path,{headers:{Authorization:`Bearer ${token}`}});
   return {plain:plain.status,authenticated:authed.status,bytes:(await authed.arrayBuffer()).byteLength};
 },{id,token:actor.token});
 result.job_before=jobSnapshot();checkpoint();
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'})).status,200);
 result.audio_decode=await page.evaluate(async id=>{
   const response=await fetch(`/api/v1/videos/${id}/original`);
   if(response.status!==200)throw new Error('original not available for audio decode');
   const ctx=new OfflineAudioContext(1,1,48000);
   const decoded=await ctx.decodeAudioData(await response.arrayBuffer());
   let peak=0;for(const sample of decoded.getChannelData(0))peak=Math.max(peak,Math.abs(sample));
   return {channels:decoded.numberOfChannels,duration:decoded.duration,sample_rate:decoded.sampleRate,peak};
 },id);
 assert.ok(result.audio_decode.peak>0.01);assert.ok(result.audio_decode.duration>=4.9);
 result.checks['browser-audio-pcm']='PASS';
 step('transcode-completion');
 result.job_observations=[];
 const deadline=Date.now()+40*60*1000;
 while(Date.now()<deadline){
   const job=jobSnapshot();result.job_observations.push({observed_at:new Date().toISOString(),...job});checkpoint();
   if(job.state==='done')break;
   assert.notEqual(job.state,'failed','transcode dead-lettered');
   console.log(`[a07] job ${job.id}: ${job.state}, attempt ${job.attempts}`);
   await new Promise(resolve=>setTimeout(resolve,30000));
 }
 assert.equal(jobSnapshot().state,'done');
 result.checks[phase]='PASS';checkpoint();
 step('advertised-hls-tree');
 const detail=await api(actor,`/api/v1/videos/${id}`);assert.equal(detail.status,200);
 assert.ok(detail.body.hls_url);assert.ok(detail.body.renditions.length>0);
 result.hls={url:detail.body.hls_url,format:detail.body.packaging_format,renditions:detail.body.renditions};
 result.assets=[];
 const visited=new Set();
 const visit=async url=>{
   if(visited.has(url))return;visited.add(url);assert.ok(visited.size<200);
   const asset=await page.evaluate(async url=>{const r=await fetch(url);const bytes=await r.arrayBuffer();return {status:r.status,bytes:bytes.byteLength,type:r.headers.get('content-type'),text:url.includes('.m3u8')?new TextDecoder().decode(bytes):null};},url);
   assert.equal(asset.status,200);assert.ok(asset.bytes>0);result.assets.push({url,status:asset.status,bytes:asset.bytes,type:asset.type});
   if(asset.text){
     assert.ok(asset.text.startsWith('#EXTM3U'));
     const uris=asset.text.split('\n').map(s=>s.trim()).filter(s=>s&&!s.startsWith('#'));
     for(const match of asset.text.matchAll(/URI="([^"]+)"/g))uris.push(match[1]);
     assert.ok(uris.length>0);
     for(const uri of uris){const next=new URL(uri,url);assert.equal(next.origin,'https://secure.video.test');await visit(next.href);}
   }
 };
 await visit(new URL(detail.body.hls_url,'https://secure.video.test').href);
 assert.ok(result.assets.some(a=>a.url.includes('.m4s')));assert.ok(result.assets.some(a=>a.url.includes('init')));
 result.checks[phase]='PASS';checkpoint();
 step('hls-browser-decode-audio-seek');
 await page.goto(`/videos/${id}`);
 result.hls_playback=await measurePlayback(page);assert.ok(result.hls_playback.src.startsWith('blob:'));
 await page.locator('#main-content').getByRole('button',{name:/^Quality: Auto/}).first().click();
 await page.getByRole('menu',{name:'Playback quality'}).getByRole('menuitemradio',{name:`${detail.body.renditions[0].height}p`,exact:true}).click();
 await expect(page.locator('#main-content').getByRole('button',{name:new RegExp(`^Quality: ${detail.body.renditions[0].height}p`)}).first()).toBeVisible();
 result.selected_quality_playback=await measurePlayback(page);
 await page.screenshot({path:join(output,'private-watch.png')});
 result.checks[phase]='PASS';checkpoint();
 step('progressive-without-ready-hls');
 // A completed tree would hide the original path. Temporarily reproduce the
 // pre-transcode state on this synthetic video, restoring it even on failure.
 const playlistState=sql(`SELECT state FROM streaming_playlists WHERE video_id='${id}'`);
 assert.equal(playlistState,'ready');
 try {
   sql(`UPDATE streaming_playlists SET state='pending' WHERE video_id='${id}'`);
   assert.ok(!(await api(actor,`/api/v1/videos/${id}`)).body.hls_url);
   await page.goto(`/videos/${id}`);
   result.progressive=await measurePlayback(page,'/original');
   assert.ok(result.progressive.src.endsWith('/original'));
   result.checks[phase]='PASS';
 } finally {
   sql(`UPDATE streaming_playlists SET state='ready' WHERE video_id='${id}'`);
   assert.ok((await api(actor,`/api/v1/videos/${id}`)).body.hls_url);
   result.checks['restore-hls-ready']='PASS';
 }
 result.status=Object.values(result.checks).every(v=>v==='PASS')?'PASS':'UNVERIFIED';
} catch(error){for(const context of browser.contexts())for(const page of context.pages())await page.screenshot({path:join(output,'private-failure.png')}).catch(()=>{});result.checks[phase]='FAIL';result.status='FAIL';writeFileSync(join(output,'private-error.txt'),error.stack,{mode:0o600});}
finally{await browser.close();checkpoint();}
console.log(`[a07] ${result.status}; ${output}`);
process.exitCode=result.status==='PASS'?0:1;
