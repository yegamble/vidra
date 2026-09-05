#!/usr/bin/env node
// A09: required real search, durable events, UI and visibility/recovery evidence.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateTarget } from './owner-auth-smoke.mjs';
assert.ok(Number(process.versions.node.split('.')[0]) >= 24, 'Node >=24 required');
assert.equal(process.env.E2E_SEARCH_SERVICE,'true','A09 requires E2E_SEARCH_SERVICE=true; no skipped search lane');
const [a03dir, actorsDir, fixture, output] = process.argv.slice(2);
assert.ok(output, 'usage: search-smoke.mjs A03_OUTPUT A04_ACTORS MP4 NEW_OUTPUT');
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
const step = name => { phase = name; console.log(`[a09] ${name}`); };
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
assert.equal(a06.vm,vm);assert.equal(a06.project,a03.project);assert.equal(a06.status,'PASS');
assert.equal(a06.fixture_sha256,hash(bytes));
const id=uuid(a06.video_id);result.video_id=id;result.required_search=true;
const title=`A09search${Date.now()}`;
result.query=title;
const checkpoint=()=>writeFileSync(join(output,'result.json'),JSON.stringify(result,null,2)+'\n');
const poll=async check=>{await expect(check).toPass({timeout:180000,intervals:[500,1000,2000]});};
const marker=()=>Number(sql('SELECT COALESCE(max(id),0) FROM search_outbox'));
const documentRow=(videoID=id)=>{
 const row=sql(`SELECT row_to_json(d) FROM (SELECT video_id,title,eligible,suppressed_reason,reconcile_run_id FROM search.documents WHERE video_id='${uuid(videoID)}') d`);
 return row?JSON.parse(row):null;
};
const eventProof=(after,type,videoID=id)=>JSON.parse(sql(`SELECT COALESCE(json_agg(e),'[]') FROM (SELECT o.id,o.event_id,o.event_type,o.state,o.attempts,(i.event_id IS NOT NULL) AS received FROM search_outbox o LEFT JOIN search.events_inbox i USING(event_id) WHERE o.id>${after} AND o.event_type='${type}' AND o.payload::text LIKE '%${uuid(videoID)}%' ORDER BY o.id) e`));
const waitEvent=async(after,type,videoID=id)=>{
 let events;
 await poll(()=>{events=eventProof(after,type,videoID);assert.ok(events.some(e=>e.state==='delivered'&&e.received));});
 return events;
};
// Sign inside the guest. The shared secret never leaves the VM or enters logs.
const internalSearch=q=>JSON.parse(guest(['python3','-c',`
import hashlib,hmac,json,subprocess,sys,time,urllib.parse,urllib.request
c=json.loads(subprocess.check_output(['docker','inspect',sys.argv[1]]))[0]
env=dict(v.split('=',1) for v in c['Config']['Env'])
ip=next(v['IPAddress'] for v in c['NetworkSettings']['Networks'].values() if v['IPAddress'])
p='/internal/v1/search';ts=str(int(time.time()))
sig=hmac.new(env['INTERNAL_SECRET'].encode(),(ts+'\\nGET\\n'+p).encode(),hashlib.sha256).hexdigest()
u='http://'+ip+':8080'+p+'?'+urllib.parse.urlencode({'q':sys.argv[2],'limit':20,'offset':0,'mode':'simple','personalized':'false'})
r=urllib.request.Request(u,headers={'X-Vidra-Internal-Auth':'v1:'+ts+':'+sig})
with urllib.request.urlopen(r,timeout=15) as response: print(response.read().decode())
`,`${a03.project}-search-1`,q]));
let actor, searchStopped=false;
try{
 step('required-search-ready');
 assert.equal(guest(['docker','inspect','--format','{{.State.Health.Status}}',`${a03.project}-search-1`]).trim(),'healthy');
 result.images=guest(['docker','inspect','--format','{{.Name}} {{.Config.Image}} {{.Image}}',`${a03.project}-api-1`,`${a03.project}-search-1`,`${a03.project}-frontend-1`]).trim().split('\n');
 actor=await login(actors.ordinary);
 const publicContext=await browser.newContext({baseURL:'https://secure.video.test',ignoreHTTPSErrors:true,viewport:{width:1600,height:1000}});
 const publicPage=await publicContext.newPage();await publicPage.goto('/');
 let lastSearchMarker=0;result.source_observations=[];
 const search=async(q=title)=>{
   lastSearchMarker=marker();
   return publicPage.evaluate(async q=>{const r=await fetch(`/api/v1/videos/search?q=${encodeURIComponent(q)}`);return {status:r.status,body:await r.json()};},q);
 };
 const assertSource=async(q,wanted)=>{
   let observation;
   await poll(()=>{
     const row=sql(`SELECT row_to_json(e) FROM (SELECT id,event_id,payload->>'source' AS source FROM search_outbox WHERE id>${lastSearchMarker} AND event_type='search.submitted' AND payload->>'query'='${q}' ORDER BY id DESC LIMIT 1) e`);
     observation=row?JSON.parse(row):null;assert.equal(observation?.source,wanted);
   });
   result.source_observations.push({phase,...observation});
 };
 result.checks[phase]='PASS';checkpoint();
 step('same-video-outbox-index-ui');
 const start=marker();
 assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{title,privacy:'public'})).status,200);
 result.upsert_events=await waitEvent(start,'video.upsert');
 await poll(()=>{const d=documentRow();assert.equal(d?.title,title);assert.equal(d?.eligible,true);});
 result.indexed=documentRow();result.internal_search=internalSearch(title);
 assert.ok(result.internal_search.ids.some(hit=>hit.video_id===id));
 const hit=await search();assert.equal(hit.status,200);assert.ok(hit.body.videos.some(v=>v.id===id));await assertSource(title,'search');
 result.search_source='search';
 const box=publicPage.getByRole('combobox',{name:/Search/});
 await box.fill(title);await box.press('Enter');
 await expect(publicPage).toHaveURL(/\/search\?q=/);
 const link=publicPage.getByRole('link',{name:title,exact:true}).first();await expect(link).toBeVisible({timeout:30000});
 result.ui_href=await link.getAttribute('href');
 await link.click();await expect(publicPage).toHaveURL(new RegExp(`/videos/${id}|/v/`));
 await expect(publicPage.getByRole('heading',{name:title,exact:true})).toBeVisible();
 await publicPage.screenshot({path:join(output,'private-search-watch.png')});
 result.checks[phase]='PASS';checkpoint();
 step('private-stale-index-rehydration');
 const privacyStart=marker();assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'private'})).status,200);
 // Freeze a stale public candidate after delivery; core must still rehydrate it.
 result.private_events=await waitEvent(privacyStart,'video.upsert');
 await poll(()=>assert.equal(documentRow()?.eligible,false));
 sql(`UPDATE search.documents SET eligible=true WHERE video_id='${id}'`);
 result.stale_private_candidate=internalSearch(title);assert.ok(result.stale_private_candidate.ids.some(v=>v.video_id===id));
 const hidden=await search();assert.equal(hidden.status,200);assert.ok(!hidden.body.videos.some(v=>v.id===id));
 await publicPage.goto(`/search?q=${encodeURIComponent(title)}`);await publicPage.waitForLoadState('networkidle');await expect(publicPage.getByRole('link',{name:title,exact:true})).toHaveCount(0);
 const denied=await publicPage.evaluate(async id=>(await fetch(`/api/v1/videos/${id}`)).status,id);assert.equal(denied,404);
 const restoreStart=marker();assert.equal((await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'})).status,200);
 await waitEvent(restoreStart,'video.upsert');await poll(()=>assert.equal(documentRow()?.eligible,true));
 result.checks[phase]='PASS';checkpoint();
 step('service-outage-local-fallback');
 guest(['docker','stop',`${a03.project}-search-1`]);searchStopped=true;
 const fallback=await search();assert.equal(fallback.status,200);assert.ok(fallback.body.videos.some(v=>v.id===id));await assertSource(title,'local');
 result.outage_source='local';
 guest(['docker','start',`${a03.project}-search-1`]);searchStopped=false;
 await poll(()=>assert.equal(guest(['docker','inspect','--format','{{.State.Health.Status}}',`${a03.project}-search-1`]).trim(),'healthy'));
 result.checks[phase]='PASS';checkpoint();
 step('missing-document-startup-reconcile');
 const oldStamp=documentRow().reconcile_run_id;const reconcileStart=marker();
 sql(`DELETE FROM search.documents WHERE video_id='${id}'`);assert.equal(documentRow(),null);
 const cold=await search();assert.equal(cold.status,200);assert.ok(cold.body.videos.some(v=>v.id===id));await assertSource(title,'local');
 guest(['docker','restart',`${a03.project}-api-1`]);
 await poll(()=>assert.equal(guest(['docker','inspect','--format','{{.State.Health.Status}}',`${a03.project}-api-1`]).trim(),'healthy'));
 await poll(()=>{const d=documentRow();assert.equal(d?.eligible,true);assert.ok(d?.reconcile_run_id);assert.notEqual(d.reconcile_run_id,oldStamp);});
 result.reconciled=documentRow();result.reconcile_events=await waitEvent(reconcileStart,'reconcile.page');
 const runID=uuid(result.reconciled.reconcile_run_id);
 await poll(()=>{
   result.reconcile_envelopes=JSON.parse(sql(`SELECT COALESCE(json_agg(e),'[]') FROM (SELECT o.event_id,o.event_type,o.state,(i.event_id IS NOT NULL) AS received FROM search_outbox o LEFT JOIN search.events_inbox i USING(event_id) WHERE o.id>${reconcileStart} AND o.payload->>'run_id'='${runID}') e`));
   for(const type of ['reconcile.begin','reconcile.page','reconcile.end'])assert.ok(result.reconcile_envelopes.some(e=>e.event_type===type&&e.state==='delivered'&&e.received));
 });
 const recovered=await search();assert.ok(recovered.body.videos.some(v=>v.id===id));await assertSource(title,'search');
 result.checks[phase]='PASS';checkpoint();
 step('delete-real-fixture-copy');
 const deletionTitle=`${title}delete`;
 const created=await api(actor,`/api/v1/channels/${encodeURIComponent(a06.channel_handle)}/videos`,'POST',{title:deletionTitle,privacy:'public'});assert.equal(created.status,201);
 const deletionID=uuid(created.body.id);result.deletion_video_id=deletionID;
 const uploaded=await actor.page.evaluate(async({id,token,encoded})=>{
   const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));const form=new FormData();form.append('file',new Blob([bytes],{type:'video/mp4'}),'a09-delete.mp4');
   const r=await fetch(`/api/v1/videos/${id}/file`,{method:'POST',headers:{Authorization:`Bearer ${token}`},body:form});return {status:r.status};
 },{id:deletionID,token:actor.token,encoded:bytes.toString('base64')});assert.ok([200,201,202].includes(uploaded.status));result.deletion_upload_status=uploaded.status;
 await poll(()=>assert.equal(Number(sql(`SELECT size_bytes FROM video_files WHERE video_id='${deletionID}' AND kind='original'`)),bytes.length));
 await poll(()=>assert.equal(documentRow(deletionID)?.eligible,true));
 assert.ok((await search(deletionTitle)).body.videos.some(v=>v.id===deletionID));
 const deletionStart=marker();assert.equal((await api(actor,`/api/v1/videos/${deletionID}`,'DELETE')).status,204);
 result.delete_events=await waitEvent(deletionStart,'video.suppress',deletionID);
 await poll(()=>assert.equal(documentRow(deletionID)?.eligible,false));
 sql(`UPDATE search.documents SET eligible=true WHERE video_id='${deletionID}'`);
 result.stale_deleted_candidate=internalSearch(deletionTitle);assert.ok(result.stale_deleted_candidate.ids.some(v=>v.video_id===deletionID));
 const gone=await search(deletionTitle);assert.equal(gone.status,200);assert.ok(!gone.body.videos.some(v=>v.id===deletionID));
 assert.equal(sql(`SELECT count(*) FROM videos WHERE id='${deletionID}'`),'0');
 await publicPage.goto(`/search?q=${encodeURIComponent(deletionTitle)}`);await publicPage.waitForLoadState('networkidle');await expect(publicPage.getByRole('link',{name:deletionTitle,exact:true})).toHaveCount(0);
 sql(`UPDATE search.documents SET eligible=false WHERE video_id='${deletionID}'`);
 result.checks[phase]='PASS';result.status='PASS';
}catch(error){result.checks[phase]='FAIL';result.status='FAIL';writeFileSync(join(output,'private-error.txt'),error.stack,{mode:0o600});}
finally{
 if(searchStopped)guest(['docker','start',`${a03.project}-search-1`]);
 if(actor){const restored=await api(actor,`/api/v1/videos/${id}`,'PATCH',{privacy:'public'}).catch(()=>null);result.restored_public=restored?.status===200;if(!result.restored_public)result.status='FAIL';}
 if(result.deletion_video_id)sql(`UPDATE search.documents SET eligible=false WHERE video_id='${uuid(result.deletion_video_id)}' AND NOT EXISTS (SELECT 1 FROM videos WHERE id='${result.deletion_video_id}')`);
 await browser.close();checkpoint();
}
console.log(`[a09] ${result.status}; ${output}`);process.exitCode=result.status==='PASS'?0:1;
