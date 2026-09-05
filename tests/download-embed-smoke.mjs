#!/usr/bin/env node
// A08 download revocation and real iframe origin policies.
import assert from 'node:assert/strict';
import { createServer } from 'node:https';
import { createServer as createHTTPServer } from 'node:http';
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
const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP secure.video.test ${ip}, MAP allowed.a08.test 127.0.0.1, MAP denied.a08.test 127.0.0.1`, '--no-proxy-server'] });
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
let actor,baseline,policy;let parent,insecureParent,activePage;
try {
 step('fixture-identity');
 for(const service of ['api','frontend']){
  const tag=service==='api'?'vidra-core:a08-source':'vidra-user:a08-source';
  assert.equal(guest(['docker','inspect','--format','{{.Image}}',`${a03.project}-${service}-1`]).trim(),prepared.images[tag]);
 }
 actor=await login(actors.ordinary);baseline=(await api(actor,`/api/v1/videos/${id}`)).body;assert.equal(baseline.privacy,'public');
 const originalPolicy=await api(actor,`/api/v1/videos/${id}/embed-privacy`);assert.equal(originalPolicy.status,200);policy=originalPolicy.body;
 result.checks[phase]='PASS';
 const ctx=await browser.newContext({baseURL:'https://secure.video.test',ignoreHTTPSErrors:true,acceptDownloads:true,viewport:{width:1600,height:1000}});
 const page=await ctx.newPage();activePage=page;result.api_responses=[];page.on('response',r=>{if(r.url().includes('/api/v1/'))result.api_responses.push({path:new URL(r.url()).pathname,status:r.status()});});
 const read=path=>page.evaluate(async path=>{const r=await fetch(path);return {status:r.status,body:await r.json()};},path);
 step('download-original-and-revoke');
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{download_enabled:true})).status,200);
 await page.goto(`/v/${baseline.short_code}`);
 const downloadable=await read(`/api/v1/videos/${id}/download`);assert.equal(downloadable.status,200);
 const downloadPaths=[...new Set(downloadable.body.files.flatMap(f=>[f.url,f.video_only_url].filter(Boolean)))];assert.ok(downloadPaths.length);result.download_paths=downloadPaths;
 result.available_downloads=await page.evaluate(async paths=>{const rows=[];for(const path of paths){const r=await fetch(path);rows.push({path,status:r.status,bytes:(await r.arrayBuffer()).byteLength});}return rows;},downloadPaths);
 for(const asset of result.available_downloads){assert.equal(asset.status,200);assert.ok(asset.bytes>0);}
 await page.locator('#main-content').getByRole('button',{name:'Download',exact:true}).click();
 const dialog=page.getByRole('dialog');await dialog.getByRole('radio',{name:/Original file/}).check();
 const pending=page.waitForEvent('download');await dialog.getByRole('button',{name:'Download',exact:true}).click();const download=await pending;
 const path=await download.path();assert.ok(path);const downloaded=readFileSync(path);assert.equal(hash(downloaded),hash(bytes));
 result.download={bytes:downloaded.length,sha256:hash(downloaded),filename:download.suggestedFilename()};
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{download_enabled:false})).status,200);
 result.revoked=[];
 for(const path of [`/api/v1/videos/${id}/download`,...downloadPaths]){const r=await read(path);assert.equal(r.status,403);assert.equal(r.body.error.code,'feature_disabled');result.revoked.push({path,status:r.status,code:r.body.error.code});}
 await page.reload();await expect(page.locator('#main-content').getByRole('button',{name:'Download',exact:true})).toHaveCount(0);
 result.streaming_after_download_revoke=await sample(page);
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{download_enabled:baseline.download_enabled})).status,200);
 result.checks[phase]='PASS';checkpoint();
 await page.goto('about:blank');await new Promise(resolve=>setTimeout(resolve,30000));
 step('real-iframe-origins');
 execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-keyout',join(output,'private-parent-key.pem'),'-out',join(output,'parent-cert.pem'),'-subj','/CN=allowed.a08.test','-days','1'],{stdio:'ignore'});
 const serveParent=(req,res)=>{res.writeHead(200,{'Content-Type':'text/html','Referrer-Policy':'origin'});res.end(`<html><body><iframe width="1100" height="750" src="https://secure.video.test/embed/${id}"></iframe></body></html>`);};
 parent=createServer({key:readFileSync(join(output,'private-parent-key.pem')),cert:readFileSync(join(output,'parent-cert.pem'))},serveParent);
 insecureParent=createHTTPServer(serveParent);await new Promise(resolve=>insecureParent.listen(0,'127.0.0.1',resolve));const httpPort=insecureParent.address().port;
 await new Promise(resolve=>parent.listen(0,'127.0.0.1',resolve));const port=parent.address().port;
 assert.equal((await api(actor,`/api/v1/videos/${id}/embed-privacy`,'PUT',{status:'whitelist',allowed_domains:['allowed.a08.test']})).status,200);
 result.embed={};
 await page.goto(`https://allowed.a08.test:${port}`);let frame=page.frames().find(f=>f.url().includes('/embed/'));assert.ok(frame);
 result.embed.context=await frame.evaluate(()=>({referrer:document.referrer,ancestors:Array.from(location.ancestorOrigins??[]),secure:isSecureContext,randomUUID:typeof crypto.randomUUID}));checkpoint();
 result.embed.allowed=await sample(frame);
 await page.goto('about:blank');await new Promise(resolve=>setTimeout(resolve,30000));
 await page.goto(`http://allowed.a08.test:${httpPort}`);frame=page.frames().find(f=>f.url().includes('/embed/'));assert.ok(frame);
 result.embed.http_context=await frame.evaluate(()=>({referrer:document.referrer,ancestors:Array.from(location.ancestorOrigins??[]),secure:isSecureContext,randomUUID:typeof crypto.randomUUID}));
 result.embed.http_allowed=await sample(frame);
 await page.goto(`http://denied.a08.test:${httpPort}`);frame=page.frames().find(f=>f.url().includes('/embed/'));assert.ok(frame);
 await expect(frame.getByText('This video can’t be embedded on this site.',{exact:true})).toBeVisible();await expect(frame.locator('video')).toHaveCount(0);result.embed.http_denied='blocked';
 await page.goto(`https://denied.a08.test:${port}`);frame=page.frames().find(f=>f.url().includes('/embed/'));assert.ok(frame);
 await expect(frame.getByText('This video can’t be embedded on this site.',{exact:true})).toBeVisible();await expect(frame.locator('video')).toHaveCount(0);result.embed.denied='blocked';
 assert.equal((await api(actor,`/api/v1/videos/${id}/embed-privacy`,'PUT',{status:'disabled'})).status,200);
 await page.goto(`/embed/${id}`);await expect(page.getByText('Embedding is disabled for this video.',{exact:true})).toBeVisible();await expect(page.locator('video')).toHaveCount(0);result.embed.disabled='blocked';
 result.checks[phase]='PASS';result.status='PASS';
}catch(error){result.status='FAIL';result.checks[phase]='FAIL';writeFileSync(join(output,'private-error.txt'),error.stack,{mode:0o600});if(activePage){await activePage.screenshot({path:join(output,'private-failure.png'),fullPage:true});result.frame_debug=await Promise.all(activePage.frames().map(async f=>({url:f.url(),text:await f.locator('body').innerText().catch(()=>'' )})));}}
finally{
 if(actor&&baseline){result.restore_download=(await api(actor,`/api/v1/videos/${id}`,'PATCH',{download_enabled:baseline.download_enabled}).catch(()=>null))?.status;}
 if(actor&&policy){result.restore_embed=(await api(actor,`/api/v1/videos/${id}/embed-privacy`,'PUT',policy).catch(()=>null))?.status;}
 if(result.restore_download!==200||result.restore_embed!==200)result.status='FAIL';
 await browser.close();if(parent)await new Promise(resolve=>parent.close(resolve));if(insecureParent)await new Promise(resolve=>insecureParent.close(resolve));checkpoint();
}
console.log(JSON.stringify({status:result.status,checks:result.checks,restore_download:result.restore_download,restore_embed:result.restore_embed}));process.exitCode=result.status==='PASS'?0:1;
