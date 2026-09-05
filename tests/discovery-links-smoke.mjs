#!/usr/bin/env node
// A08 metadata, discovery transitions and synthetic source-UUID routing.
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
let actor,baseline,alias;
try{
 step('fixture-identity');
 for(const service of ['api','frontend']){const tag=service==='api'?'vidra-core:a08-source':'vidra-user:a08-source';assert.equal(guest(['docker','inspect','--format','{{.Image}}',`${a03.project}-${service}-1`]).trim(),prepared.images[tag]);}
 actor=await login(actors.ordinary);const detail=await api(actor,`/api/v1/videos/${id}`);assert.equal(detail.status,200);baseline=detail.body;assert.equal(baseline.privacy,'public');assert.equal(actor.user.unlisted,false);
 const code=baseline.short_code,canonical=`https://secure.video.test/v/${code}`;result.short_code=code;
 const ctx=await browser.newContext({baseURL:'https://secure.video.test',ignoreHTTPSErrors:true});const page=await ctx.newPage();
 await page.goto(`/v/${code}`);result.checks[phase]='PASS';
 const snapshot=()=>page.evaluate(async({id,code,title})=>{
  const json=async path=>{const r=await fetch(path,{cache:'no-store'});if(r.status!==200)throw new Error(path+' status '+r.status);return r.json();};
  const videos=await json('/api/v1/videos?limit=100');const search=await json('/api/v1/videos/search?q='+encodeURIComponent(title));
  const xml=async path=>{const r=await fetch(path,{cache:'no-store'});if(r.status!==200)throw new Error(path+' status '+r.status);return new DOMParser().parseFromString(await r.text(),'text/xml');};
  const feed=await xml('/feeds/videos.xml'),sitemap=await xml('/sitemap.xml');
  return {feed:videos.videos.some(v=>v.id===id),search:search.videos.some(v=>v.id===id),rss:[...feed.querySelectorAll('item link')].some(n=>n.textContent===location.origin+'/v/'+code),sitemap:[...sitemap.querySelectorAll('loc')].some(n=>n.textContent===location.origin+'/v/'+code)};
 },{id,code,title:baseline.title});
 const visibility=async expected=>{let found;await expect(async()=>{found=await snapshot();for(const value of Object.values(found))assert.equal(value,expected);}).toPass({timeout:30000});return found;};
 step('canonical-metadata-distribution');
 result.public_discovery=await visibility(true);
 result.metadata=await page.evaluate(()=>({canonical:document.querySelector('link[rel="canonical"]')?.href,og_url:document.querySelector('meta[property="og:url"]')?.content,og_title:document.querySelector('meta[property="og:title"]')?.content,oembed:document.querySelector('link[type="application/json+oembed"]')?.href}));
 assert.equal(result.metadata.canonical,canonical);assert.equal(result.metadata.og_url,canonical);assert.equal(result.metadata.og_title,baseline.title);assert.ok(result.metadata.oembed);
 result.distribution=await page.evaluate(async({id,code,handle})=>{
  const rows=[];
  for(const path of ['/feeds/videos.xml',`/feeds/videos.xml?channel=${handle}`,'/sitemap.xml',`/services/oembed?url=${encodeURIComponent(location.origin+'/v/'+code)}`]){
   const r=await fetch(path,{cache:'no-store'}),text=await r.text();
   if(path.startsWith('/services/')){rows.push({path,status:r.status,body:JSON.parse(text)});continue;}
   const xml=new DOMParser().parseFromString(text,'text/xml');rows.push({path,status:r.status,items:[...xml.querySelectorAll('item')].map(n=>({link:n.querySelector('link')?.textContent,guid:n.querySelector('guid')?.textContent})),locations:[...xml.querySelectorAll('loc')].map(n=>n.textContent)});
  }return rows;
 },{id,code,handle:baseline.channel_handle});
 for(const row of result.distribution){assert.equal(row.status,200);if(row.items?.length)assert.ok(row.items.some(i=>i.link===canonical&&i.guid===`https://secure.video.test/videos/${id}`));}
 assert.ok(result.distribution.find(r=>r.path==='/sitemap.xml').locations.includes(canonical));
 const oembed=result.distribution.find(r=>r.body).body;assert.equal(oembed.title,baseline.title);assert.ok(oembed.html.includes(`https://secure.video.test/embed/${id}`));
 result.checks[phase]='PASS';checkpoint();
 step('unlisted-video-discovery');
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'unlisted'})).status,200);result.unlisted=await visibility(false);
 await page.goto(`/v/${code}`);result.unlisted_playback=await sample(page);
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'})).status,200);await visibility(true);
 result.checks[phase]='PASS';checkpoint();
 await page.goto('about:blank');await new Promise(resolve=>setTimeout(resolve,30000));await page.goto(`/v/${code}`);
 step('account-unlisted-discovery');
 assert.equal((await api(actor,'/api/v1/auth/me','PATCH',{unlisted:true})).status,200);result.account_unlisted=await visibility(false);
 result.account_direct=await page.evaluate(async({id,handle})=>({video:(await fetch(`/api/v1/videos/${id}`,{cache:'no-store'})).status,channel:(await fetch(`/api/v1/channels/${handle}`,{cache:'no-store'})).status}),{id,handle:baseline.channel_handle});
 assert.deepEqual(result.account_direct,{video:200,channel:200});
 assert.equal((await api(actor,'/api/v1/auth/me','PATCH',{unlisted:false})).status,200);result.account_restored=await visibility(true);
 result.checks[phase]='PASS';checkpoint();
 step('private-distribution-refusal');
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'private'})).status,200);result.private=await visibility(false);
 result.private_oembed=await page.evaluate(async url=>(await fetch(url,{cache:'no-store'})).status,result.metadata.oembed);assert.equal(result.private_oembed,401);
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'})).status,200);
 result.checks[phase]='PASS';checkpoint();
 step('source-uuid-aliases');
 assert.equal(sql(`SELECT coalesce(peertube_uuid::text,'') FROM videos WHERE id='${id}'`),'');alias=uuid(crypto.randomUUID());
 assert.equal(sql(`UPDATE videos SET peertube_uuid='${alias}' WHERE id='${id}' AND peertube_uuid IS NULL RETURNING id`),id+'\nUPDATE 1');
 const alphabet='123456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ';let n=BigInt('0x'+alias.replaceAll('-','')),sid='';while(n){sid=alphabet[Number(n%58n)]+sid;n/=58n;}sid=sid.padStart(22,'1');
 result.synthetic_source_uuid=alias;result.aliases=[];
 for(const path of [`/w/${sid}`,`/videos/watch/${alias}`]){
  const response=await page.goto(path+'?t=2');assert.equal(response.status(),200);assert.equal(new URL(page.url()).pathname,`/v/${code}`);assert.equal(new URL(page.url()).searchParams.get('t'),'2');
  result.aliases.push({path,final_url:page.url(),playback:await sample(page)});
  await page.goto('about:blank');await new Promise(resolve=>setTimeout(resolve,30000));
 }
 result.checks[phase]='PASS';result.status='PASS';
}catch(error){result.status='FAIL';result.checks[phase]='FAIL';writeFileSync(join(output,'private-error.txt'),error.stack,{mode:0o600});}
finally{
 if(alias){result.alias_cleanup=sql(`UPDATE videos SET peertube_uuid=NULL WHERE id='${id}' AND peertube_uuid='${alias}' RETURNING id`)===id+'\nUPDATE 1';}
 if(actor&&baseline){result.restore_privacy=(await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:baseline.privacy}).catch(()=>null))?.status;result.restore_account=(await api(actor,'/api/v1/auth/me','PATCH',{unlisted:actor.user.unlisted}).catch(()=>null))?.status;}
 if(result.restore_privacy!==200||result.restore_account!==200||(alias&&!result.alias_cleanup))result.status='FAIL';
 await browser.close();checkpoint();
}
console.log(JSON.stringify({status:result.status,checks:result.checks,restore_privacy:result.restore_privacy,restore_account:result.restore_account,alias_cleanup:result.alias_cleanup}));process.exitCode=result.status==='PASS'?0:1;
