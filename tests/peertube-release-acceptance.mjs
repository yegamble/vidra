#!/usr/bin/env node
// Packaged admin UI, real import worker and persisted readback on the retained host.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';

const [stageArg, mode, label = mode] = process.argv.slice(2);
assert.ok(stageArg && ['preview', 'import', 'repeat', 'schema-refusal', 'search', 'playback'].includes(mode));
assert.match(label, /^[a-z][a-z0-9-]*$/);
assert.equal(process.env.COMPOSE_PROJECT_NAME, 'vidra-release-acceptance');
const stage = resolve(stageArg), baseline = '/root/vidra-v064-runtime';
const output = join(stage, `${label}-browser.json`);
assert.ok(!existsSync(output), 'preserve old results; use a separate attempt directory');
const result = { status: 'UNVERIFIED', started_at: new Date().toISOString(), mode, checks: {}, requests: [], commands: [] };
const save = () => writeFileSync(output, JSON.stringify(result, null, 2) + '\n', { mode: 0o600 });
const host = args => {
  const record = { argv: args, started_at: new Date().toISOString() }; result.commands.push(record);
  try {
    const text = execFileSync(args[0], args.slice(1), { cwd: '/opt/vidra', encoding: 'utf8', timeout: 60000, stdio: ['ignore', 'pipe', 'pipe'] });
    record.exit_code = 0; return text.trim();
  } catch (error) { record.exit_code = error.status ?? 'TIMEOUT'; throw error; }
};
const sql = query => {
  assert.ok(query.startsWith('SELECT '), 'destination evidence is read only');
  return host(['bash', 'deploy/compose.sh', 'exec', '-T', 'postgres', 'psql', '-U', 'vidra', '-d', 'vidra', '-At', '-v', 'ON_ERROR_STOP=1', '-c', query]);
};
const catalogue = () => Object.fromEntries(['users', 'channels', 'videos', 'comments', 'playlists', 'playlist_items', 'channel_follows', 'video_ratings', 'video_tags', 'video_chapters', 'streaming_playlists', 'video_files', 'captions'].map(table =>
  [table, Number(sql(`SELECT count(*) FROM ${table}`))]));
const fingerprints = () => Object.fromEntries(Object.keys(catalogue()).map(table => [table,
  sql(`SELECT md5(COALESCE(string_agg(row::text, E'\\n' ORDER BY row::text),'')) FROM (SELECT to_jsonb(t) AS row FROM ${table} t) s`)]));
const imageSnapshot = () => {
  const candidate = JSON.parse(readFileSync(join(baseline, 'candidate.json')));
  const images = {};
  for (const [service, repo] of Object.entries({ api: 'vidra-core', frontend: 'vidra-user', search: 'vidra-search' })) {
    const cid = host(['bash', 'deploy/compose.sh', 'ps', '-q', service]);
    const c = JSON.parse(host(['docker', 'inspect', cid]))[0];
    const i = JSON.parse(host(['docker', 'image', 'inspect', c.Image]))[0];
    assert.ok(c.State.Running && i.RepoDigests.includes(candidate.images[repo].reference));
    assert.equal(c.Config.Image, candidate.images[repo].reference);
    assert.equal(i.Os + '/' + i.Architecture, 'linux/amd64');
    assert.equal(i.Config.Labels['org.opencontainers.image.revision'], candidate.images[repo].revision);
    images[service] = { container_id: cid, image_id: i.Id, reference: c.Config.Image, revision: candidate.images[repo].revision };
  }
  return images;
};
let browser, phase = 'login';
try {
  const { chromium, expect } = createRequire(join(baseline, 'browser/package.json'))('@playwright/test');
  assert.equal(JSON.parse(readFileSync(join(stage, 'preparation.json'))).status, 'PASS');
  result.images_before = imageSnapshot();
  result.tool_sha256 = createHash('sha256').update(readFileSync(new URL(import.meta.url))).digest('hex');
  result.node = process.version;
  browser = await chromium.launch({ args: ['--host-resolver-rules=MAP secure.video.test 127.0.0.1', '--no-proxy-server', '--autoplay-policy=no-user-gesture-required'] });
  result.browser = browser.version();
  const context = await browser.newContext({ baseURL: 'https://secure.video.test', ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage(); page.setDefaultTimeout(60000);
  const owner = JSON.parse(readFileSync(join(baseline, 'private/owner.json')));
  await page.goto('/login');
  await page.getByLabel('Email or username', { exact: true }).fill(owner.email);
  await page.getByLabel('Password', { exact: true }).fill(owner.password);
  const login = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/login') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const response = await login; assert.equal(response.status(), 200);
  let auth = await response.json(); assert.equal(auth.user.role, 'admin');
  page.on('response', async r => {
    if (r.url().endsWith('/api/v1/auth/refresh') && r.status() === 200) auth = await r.json();
  });
  await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible();
  const api = async (path, method = 'GET', body, token = auth.token) => {
    for (let attempt = 0; attempt < 4; attempt++) {
      const r = await page.evaluate(async ({ path, method, body, token }) => {
        const r = await fetch(path, { method, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
        return { status: r.status, retry_after: r.headers.get('retry-after'), body: await r.json() };
      }, { path, method, body, token });
      result.requests.push({ path, method, status: r.status, retry_after: r.retry_after }); save();
      if (r.status !== 429) return r;
      const seconds = Number(r.retry_after); assert.ok(seconds > 0 && seconds <= 120);
      await page.waitForTimeout((seconds + 1) * 1000);
    }
    throw new Error('request remained rate limited');
  };
  assert.equal((await api('/api/v1/admin/peertube-import', 'GET', undefined, '')).status, 401);
  assert.equal((await api('/api/v1/admin/peertube-import', 'POST', { mode: 'dry_run' }, '')).status, 401);
  result.checks.anonymous_denied = 'PASS';
  result.catalogue_before = catalogue();
  result.content_before = fingerprints();

  if (!['search', 'playback'].includes(mode)) {
    phase = 'launch-through-admin-ui';
    await page.goto('/admin/import-peertube');
    await expect(page.getByRole('heading', { name: 'Import from PeerTube', exact: true })).toBeVisible();
    await page.getByLabel('Media', { exact: true }).selectOption('copy');
    await page.getByLabel('Conflict policy', { exact: true }).selectOption('skip');
    const pending = page.waitForResponse(r => r.url().endsWith('/api/v1/admin/peertube-import') && r.request().method() === 'POST');
    await page.getByRole('button', { name: ['preview', 'schema-refusal'].includes(mode) ? 'Preview (dry run)' : 'Start import', exact: true }).click();
    const launched = await pending; assert.equal(launched.status(), 202);
    const initial = await launched.json(); result.run_id = initial.id;
    const expectedMode = ['preview', 'schema-refusal'].includes(mode) ? 'dry_run' : 'run';
    assert.equal(initial.mode, expectedMode);
    assert.equal(initial.media_mode, 'copy'); assert.equal(initial.acknowledged_schema_version, null);
    phase = 'worker-completion';
    let run;
    await expect(async () => {
      const current = await api(`/api/v1/admin/peertube-import/${initial.id}`); assert.equal(current.status, 200);
      run = current.body; assert.ok(['done', 'failed'].includes(run.state));
    }).toPass({ timeout: 600000, intervals: [2000, 4000, 5000] });
    assert.equal(run.mode, expectedMode);
    writeFileSync(join(stage, 'private', `${label}-run.json`), JSON.stringify(run, null, 2), { mode: 0o600 });
    result.run = { id: run.id, state: run.state, mode: run.mode, media_mode: run.media_mode, source_version: run.source_version,
      acknowledged_schema_version: run.acknowledged_schema_version, error_code: run.error_code ?? null,
      entities: run.report?.entities, conflict_count: run.report?.conflicts?.length ?? 0, started_at: run.started_at, finished_at: run.finished_at };
    if (mode === 'schema-refusal') {
      assert.equal(run.state, 'failed'); assert.equal(run.error_code, 'unverified_schema'); assert.equal(run.source_version, 1040);
    } else {
      assert.equal(run.state, 'done'); assert.equal(run.source_version, 970);
      for (const kind of ['user', 'channel', 'video', 'video_file', 'hls_playlist', 'video_no_media', 'comment', 'caption', 'tag', 'chapter', 'rating', 'playlist', 'playlist_item', 'follow']) {
        assert.ok(run.report.entities[kind], `missing entity report: ${kind}`);
      }
      for (const counts of Object.values(run.report.entities)) {
        for (const key of ['planned', 'imported', 'updated', 'skipped', 'failed', 'unsupported']) assert.ok(Number.isInteger(counts[key]) && counts[key] >= 0);
        assert.equal(counts.failed, 0);
      }
      assert.equal(run.report.entities.video_no_media?.imported ?? 0, 0);
      if (mode === 'preview') {
        assert.equal(run.report.entities.video.planned, 7);
        assert.equal(run.report.entities.user.planned, 6);
      }
      if (mode === 'import') assert.equal(run.report.entities.video.imported, 7);
      if (mode === 'repeat') for (const counts of Object.values(run.report.entities)) {
        assert.equal(counts.imported, 0); assert.equal(counts.updated, 0);
      }
      if (mode === 'repeat') assert.equal(run.report.entities.video.skipped, 7);
    }
    result.catalogue_after = catalogue();
    result.content_after = fingerprints();
    if (mode !== 'import') {
      assert.deepEqual(result.catalogue_after, result.catalogue_before);
      assert.deepEqual(result.content_after, result.content_before);
    } else {
      const delta = { users: 6, channels: 6, videos: 7, comments: 4, playlists: 1, playlist_items: 2,
        channel_follows: 1, video_ratings: 1, video_tags: 12, video_chapters: 2, streaming_playlists: 6, video_files: 26, captions: 1 };
      for (const [table, count] of Object.entries(delta)) assert.equal(result.catalogue_after[table] - result.catalogue_before[table], count);
    }
    result.checks[phase] = 'PASS';
    phase = 'persisted-ui-report';
    const refresh = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/refresh'));
    await page.reload(); const rotated = await refresh; assert.equal(rotated.status(), 200); auth = await rotated.json();
    const panel = page.getByRole('region', { name: 'Import run', exact: true });
    await expect(panel).toBeVisible();
    await expect(panel.getByText(`PeerTube schema v${run.source_version}`, { exact: true })).toBeVisible();
    await expect(panel.getByText(run.state === 'done' ? 'Done' : 'Failed', { exact: true })).toBeVisible();
    if (run.report) for (const [kind, counts] of Object.entries(run.report.entities)) {
      const row = panel.getByRole('row').filter({ has: page.getByRole('rowheader', { name: kind, exact: true }) });
      await expect(row).toHaveCount(1);
      await expect(row.getByRole('cell')).toHaveText(['planned', 'imported', 'updated', 'skipped', 'failed', 'unsupported'].map(k => String(counts[k])));
    }
    const readback = await api(`/api/v1/admin/peertube-import/${initial.id}`);
    assert.equal(readback.body.state, run.state); assert.deepEqual(readback.body.report, run.report);
    if (mode === 'schema-refusal') {
      await expect(page.getByRole('button', { name: 'Start import', exact: true })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Preview (dry run)', exact: true })).toBeDisabled();
    }
    await page.screenshot({ path: join(stage, `${label}.png`) });
    result.checks[phase] = 'PASS';
  } else if (mode === 'search') {
    phase = 'imported-video-browser-search';
    const searchRequests = () => Number(host(['python3', '-c', `
import json,subprocess,urllib.request
c=json.loads(subprocess.check_output(['docker','inspect', '${result.images_before.search.container_id}']))[0]
ip=next(v['IPAddress'] for v in c['NetworkSettings']['Networks'].values() if v['IPAddress'])
with urllib.request.urlopen('http://'+ip+':8080/metrics',timeout=15) as r: lines=r.read().decode().splitlines()
print(sum(float(s.rsplit(' ',1)[1]) for s in lines if s.startswith('vidra_search_http_requests_total{') and 'method="GET"' in s and 'route="/internal/v1/search"' in s and 'status_class="2xx"' in s))
`]));
    const expected = JSON.parse(sql("SELECT json_agg(id) FROM videos WHERE title IN ('Migration fixture progressive','Migration fixture hls_only','Migration fixture split_audio')"));
    assert.equal(expected.length, 3);
    await page.goto('/');
    result.search = { requests_before: searchRequests(), attempts: [] };
    const pending = () => page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/videos/search' && new URL(r.url()).searchParams.get('q') === 'Migration fixture');
    let next = pending();
    const box = page.getByRole('combobox', { name: /Search/ });
    await box.fill('Migration fixture'); await box.press('Enter');
    let response;
    for (let i = 0; i < 4; i++) {
      response = await next;
      result.search.attempts.push({ status: response.status(), retry_after: await response.headerValue('retry-after') });
      if (response.status() !== 429) break;
      const seconds = Number(await response.headerValue('retry-after')); assert.ok(seconds > 0 && seconds <= 120);
      await page.waitForTimeout((seconds + 1) * 1000); next = pending(); await page.reload();
    }
    assert.equal(response.status(), 200);
    result.search.ids = (await response.json()).videos.map(v => v.id);
    assert.deepEqual([...result.search.ids].sort(), [...expected].sort());
    await expect(async () => {
      result.search.requests_after = searchRequests(); assert.ok(result.search.requests_after > result.search.requests_before);
    }).toPass({ timeout: 15000 });
    await page.screenshot({ path: join(stage, `${label}.png`) });
    await page.getByRole('link', { name: 'Migration fixture hls_only', exact: true }).first().click();
    await expect(page.getByRole('heading', { name: 'Migration fixture hls_only', exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Migration fixture hls_only', exact: true })).toBeVisible();
    result.checks[phase] = 'PASS';
  } else {
    phase = 'source-disconnected-playback';
    result.source_running = host(['docker', 'inspect', 'vidra-v064-migration-source-20260911', '--format', '{{.State.Running}}']);
    assert.equal(result.source_running, 'false');
    const mounts = JSON.parse(host(['docker', 'inspect', host(['bash', 'deploy/compose.sh', 'ps', '-q', 'api']), '--format', '{{json .Mounts}}']));
    assert.ok(!mounts.some(m => m.Destination === '/peertube-source'));
    result.source_media_unmounted = true;
    const videos = JSON.parse(sql("SELECT json_agg(v) FROM (SELECT id,title,privacy FROM videos WHERE title LIKE 'Migration fixture %' ORDER BY title) v"));
    result.playback = [];
    for (const item of videos.filter(v => ['Migration fixture progressive', 'Migration fixture hls_only', 'Migration fixture split_audio'].includes(v.title))) {
      await page.goto(`/videos/${item.id}`);
      await expect(page.getByRole('heading', { name: item.title, exact: true })).toBeVisible();
      const video = page.getByTestId('video-player').first().locator('video');
      await expect(async () => assert.ok(await video.evaluate(v => v.readyState >= 2))).toPass({ timeout: 90000 });
      const sample = () => video.evaluate(v => ({ time: v.currentTime, frames: v.getVideoPlaybackQuality().totalVideoFrames,
        audio_bytes: v.webkitAudioDecodedByteCount ?? 0, error: v.error?.message ?? null, muted: v.muted }));
      await video.evaluate(v => { v.pause(); v.currentTime = 0; v.muted = false; });
      const start = await sample(); await video.evaluate(v => v.play());
      let end;
      await expect(async () => { end = await sample(); assert.ok(end.time - start.time >= 2 && end.frames > start.frames && end.audio_bytes > start.audio_bytes); assert.equal(end.error, null); }).toPass({ timeout: 60000 });
      result.playback.push({ id: item.id, title: item.title, start, end }); save();
      await page.screenshot({ path: join(stage, `${label}-${item.title.split(' ').at(-1)}.png`) });
    }
    assert.equal(result.playback.length, 3);
    result.checks[phase] = 'PASS';
  }
  result.images_after = imageSnapshot();
  assert.deepEqual(result.images_after, result.images_before);
  result.status = 'PASS';
} catch (error) {
  result.status = 'FAIL'; result.failed_phase = phase;
  writeFileSync(join(stage, 'private', `${label}-error.txt`), String(error.stack), { mode: 0o600 });
} finally {
  await browser?.close(); result.finished_at = new Date().toISOString(); save();
}
console.log(JSON.stringify({ status: result.status, mode, failed_phase: result.failed_phase }));
process.exitCode = result.status === 'PASS' ? 0 : 1;
