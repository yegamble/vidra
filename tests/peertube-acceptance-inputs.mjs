// Representative expectations are independent, hash-bound source inputs.
// Usage: driver STAGE MODE LABEL BASELINE INPUTS_JSON (preview/import/repeat).
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

export const CATALOGUE_TABLES = 'users channels videos comments playlists playlist_items channel_follows video_ratings video_tags video_chapters streaming_playlists video_files captions'.split(' ');
const COUNTERS = ['planned', 'imported', 'updated', 'skipped', 'failed', 'unsupported'];
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const count = value => Number.isSafeInteger(value) && value >= 0;
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

export function loadAcceptanceInputs(path, candidatePath, mode) {
  assert.ok(['preview', 'import', 'repeat'].includes(mode),
    'representative mode supports preview/import/repeat only; fixture marker actions are forbidden');
  const bytes = readFileSync(path);
  const spec = JSON.parse(bytes);
  assert.ok(spec.schema_version === 1 && spec.scope === 'representative', 'representative scope required');
  assert.ok(sha(spec.candidate_sha256), 'candidate hash required');
  const candidate = readFileSync(candidatePath);
  assert.equal(digest(candidate), spec.candidate_sha256, 'candidate hash mismatch');
  const records = {};
  for (const key of ['source', 'expectations']) {
    assert.ok(object(spec[key]) && typeof spec[key].path === 'string' && sha(spec[key].sha256),
      'hash-bound ' + key + ' record required');
    const content = readFileSync(resolve(dirname(path), spec[key].path));
    assert.equal(digest(content), spec[key].sha256, key + ' hash mismatch');
    records[key] = JSON.parse(content);
  }
  const { source, expectations } = records;
  assert.ok(object(source) && Number.isSafeInteger(source.peertube_schema_version) &&
    source.peertube_schema_version > 0 && sha(source.snapshot_sha256) && sha(source.media_manifest_sha256),
  'source provenance requires schema, snapshot and media manifest hashes');
  assert.ok(object(expectations), 'expectations record required');
  assert.deepEqual(Object.keys(expectations.catalogue_delta ?? {}).sort(), [...CATALOGUE_TABLES].sort(),
    'catalogue tables must be explicit and complete');
  for (const value of Object.values(expectations.catalogue_delta)) {
    assert.ok(count(value), 'catalogue delta must be a nonnegative integer');
  }
  for (const action of ['preview', 'import', 'repeat']) {
    const entities = expectations[action];
    assert.ok(object(entities) && object(entities.video) && object(entities.video_no_media),
      action + ' requires video and missing-media expectations');
    if (action === 'preview') assert.ok(object(entities.user), 'preview requires user expectations');
    for (const [kind, counters] of Object.entries(entities)) {
      assert.match(kind, /^[a-z_]+$/, 'invalid entity kind');
      assert.ok(object(counters) && Object.keys(counters).length > 0, 'entity counters required');
      for (const [key, value] of Object.entries(counters)) {
        assert.ok(COUNTERS.includes(key), 'unknown entity counter');
        assert.ok(count(value), 'entity counter must be a nonnegative integer');
        assert.ok(key !== 'failed' || value === 0, 'failed entities cannot be accepted');
      }
    }
    const key = action === 'preview' ? 'planned' : action === 'import' ? 'imported' : 'skipped';
    assert.ok(count(entities.video[key]) && count(entities.video_no_media[action === 'preview' ? 'planned' : 'imported']),
      action + ' requires explicit video and missing-media counts');
    if (action === 'preview') assert.ok(count(entities.user.planned), 'preview user count required');
  }
  return { source, expectations, provenance: { scope: spec.scope, inputs_sha256: digest(bytes),
    candidate_sha256: digest(candidate), source_sha256: spec.source.sha256,
    expectations_sha256: spec.expectations.sha256 } };
}

export function assertExpectedReport(input, mode, run) {
  assert.equal(run.source_version, input.source.peertube_schema_version, 'source schema differs');
  assert.equal(run.acknowledged_schema_version, null, 'representative schema acknowledgement is forbidden');
  for (const [kind, counters] of Object.entries(run.report?.entities ?? {})) {
    assert.equal(counters.unsupported ?? 0, input.expectations[mode][kind]?.unsupported ?? 0,
      kind + '.unsupported differs from source expectations');
  }
  for (const [kind, counters] of Object.entries(input.expectations[mode])) {
    for (const [key, value] of Object.entries(counters)) {
      assert.equal(run.report?.entities?.[kind]?.[key], value, kind + '.' + key + ' differs from source expectations');
    }
  }
}

export function assertPreparedSource(input, preparation) {
  assert.equal(preparation.scope, 'representative', 'a generated fixture cannot certify a real source');
  assert.equal(preparation.candidate_sha256, input.provenance.candidate_sha256, 'prepared candidate differs');
  assert.equal(preparation.source_snapshot_sha256, input.source.snapshot_sha256, 'prepared source snapshot differs');
  assert.equal(preparation.source_media_manifest_sha256, input.source.media_manifest_sha256, 'prepared source media differs');
}
