"""Guard archive handling, candidate derivation and the sole Compose adaptation of the COPY rehearsal."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import peertube_release_acceptance as p
import peertube_release_export as export_tool
from peertube_release_checks import execute, original_files, match_assets
from peertube_release_export import collect_secrets, env_secrets, json_values, owner_password, reject_secrets

ROOT = Path(__file__).resolve().parents[1]
B2_SPEC = {'bucket': 'vidra-acceptance-v065-20260914-media', 'bucket_id': 'e565124b996984e8a7070215',
           'region': 'us-east-005', 'endpoint': 's3.us-east-005.backblazeb2.com'}


class PeerTubeReleaseTests(unittest.TestCase):
    def test_export_rejects_pem_content_but_not_scanner_literals(self):
        marker = '-----BEGIN ' + 'RSA PRIVATE KEY-----'
        reject_secrets(repr(marker), [])
        for text in (marker + '\nREDACTED', marker + r'\nREDACTED', 'prefix-test-secret-suffix', '$2b$12$' + 'A' * 53):
            with self.assertRaises(AssertionError):
                reject_secrets(text, ['test-secret'])

    def test_byte_equal_files_must_belong_to_correct_video(self):
        source = [{'source_id': 'one', 'filename': 'a'}, {'source_id': 'two', 'filename': 'b'}]
        match_assets(source, source, 'filename')
        for wrong in ([source[0], source[0]],
                      [{'source_id': 'one', 'filename': 'b'}, {'source_id': 'two', 'filename': 'a'}]):
            with self.assertRaises(ValueError):
                match_assets(source, wrong, 'filename')

    def test_progressive_reconciliation_excludes_image_metadata(self):
        originals = [{'kind': 'original', 'storage_key': str(n)} for n in range(5)]
        images = [{'kind': kind} for kind in ('thumbnail', 'storyboard', 'storyboard_vtt') for _ in range(7)]
        self.assertEqual(original_files(originals + images), originals)
        with self.assertRaises(ValueError):
            original_files(originals[:4] + images)

    def archive(self, name, kind=tarfile.REGTYPE):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            archive.addfile(member)
        data.seek(0)
        return tarfile.open(fileobj=data)

    def test_only_regular_media_is_extracted_read_only(self):
        for name in ('source-config8/production.yaml', 'source-media8/logs/server.log', '._source-media8'):
            with self.archive(name) as archive:
                self.assertEqual(list(p.media_members(archive)), [])
        with self.archive('source-media8/web-videos/a.mp4') as archive:
            self.assertEqual(list(p.media_members(archive))[0].mode, 0o444)

    def test_traversal_and_links_are_refused(self):
        for name, kind in [('source-media8/../../outside', tarfile.REGTYPE),
                           ('source-media8/link', tarfile.SYMTYPE)]:
            with self.archive(name, kind) as archive:
                with self.assertRaises(ValueError):
                    list(p.media_members(archive))

    def test_mount_preserves_images_and_existing_volumes(self):
        original = ('volumes:\n  - media_data:/app/data\n  - transcode_tmp:/scratch\nimage: frozen\n'
                    'services:\n  prep-volumes:\n    volumes:\n      - media_data:/app/data\n')
        changed = p.source_mount(original, '/root/rehearsal/source-media8')
        self.assertEqual(changed.replace('  - /root/rehearsal/source-media8:/peertube-source:ro\n', ''), original)
        for bad in ('', original + original):
            with self.assertRaises(ValueError):
                p.source_mount(bad, '/root/rehearsal/source-media8')


class MigrationDrillCandidateTests(unittest.TestCase):
    """The drill must take its release from the baseline it is run against.

    Hard-coding v0.6.4 made the harness unrunnable on the v0.6.5 host, and —
    worse — a literal that still parses on a newer host would have named the
    wrong release in the evidence it produced.
    """

    def baseline(self, tmp, storage):
        (tmp / 'storage.json').write_text(json.dumps(storage) + '\n')
        return tmp

    def test_release_tag_comes_from_the_committed_candidate(self):
        candidate = json.loads((ROOT / 'docs/evidence/release-v0.6.5-verification/manifest.json').read_text())
        self.assertEqual(p.release_tag(candidate), 'v0.6.5')
        self.assertEqual(p.frozen_cli_sha256(candidate, 'v0.6.5'),
                         candidate['assets']['vidra_v0.6.5_linux_amd64']['sha256'])
        for bad in ({'tag': 'v0.6'}, {'tag': 'main'}, {'tag': 'v0.6.5-rc1'}, {'tag': None}, {}):
            with self.assertRaises(ValueError):
                p.release_tag(bad)

    def test_frozen_cli_asset_key_is_keyed_to_the_tag(self):
        candidate = {'assets': {'vidra_v0.6.5_linux_amd64': {'sha256': 'a' * 64}}}
        self.assertEqual(p.frozen_cli_sha256(candidate, 'v0.6.5'), 'a' * 64)
        # A baseline that ships no asset for this release must say so, not
        # compare the installed CLI against a KeyError or another release.
        with self.assertRaises(ValueError):
            p.frozen_cli_sha256(candidate, 'v0.6.4')

    def test_scope_prose_names_the_release_under_rehearsal(self):
        self.assertIn('packaged v0.6.5 admin import', p.scope('v0.6.5'))
        self.assertIn('packaged v0.6.4 admin import', p.scope('v0.6.4'))

    def test_source_container_is_named_for_release_and_day(self):
        self.assertEqual(p.source_container('v0.6.5', '20260914'), 'vidra-v065-migration-source-20260914')
        self.assertEqual(p.source_container('v0.6.4', '20260911'), 'vidra-v064-migration-source-20260911')
        self.assertRegex(p.source_container('v0.6.5'), r'^vidra-v065-migration-source-[0-9]{8}$')
        for bad in ('main', 'v0.6', 'v0.6.5-rc1'):
            with self.assertRaises(ValueError):
                p.source_container(bad)

    def test_bucket_comes_from_the_baseline_storage_record(self):
        with tempfile.TemporaryDirectory() as name:
            baseline = self.baseline(Path(name), {'backend': 'b2', 'spec': B2_SPEC})
            self.assertEqual(p.baseline_storage(baseline, 'v0.6.5'), B2_SPEC)
            # The recorded bucket must belong to the release being rehearsed.
            with self.assertRaises(ValueError) as caught:
                p.baseline_storage(baseline, 'v0.6.4')
            self.assertIn('v0.6.4 acceptance bucket', str(caught.exception))

    def test_local_storage_baseline_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            baseline = self.baseline(Path(name), {'backend': 'local'})
            with self.assertRaises(ValueError) as caught:
                p.baseline_storage(baseline, 'v0.6.5')
            self.assertIn('B2', str(caught.exception))
            self.assertIn('local', str(caught.exception))


class ExportSecretSourceTests(unittest.TestCase):
    """Every named secret source must exist and yield a value.

    The scrub is the only thing standing between the private stage and a
    published archive: a missing key file must refuse the export, never quietly
    scan for one credential fewer.
    """

    def test_missing_or_empty_secret_source_refuses_the_export(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            env = tmp / 'source.env'
            env.write_text('# comment\nPOSTGRES_PASSWORD=generated-secret-value\nPOSTGRES_DB=peertube\n')
            owner = tmp / 'owner.json'
            owner.write_text(json.dumps({'password': 'owner-secret-value'}))
            key = tmp / 'b2-key.json'
            key.write_text(json.dumps({'access_key': 'access-value-x', 'secret_key': 'secret-value-x'}))
            self.assertEqual(collect_secrets([(env, env_secrets), (owner, owner_password), (key, json_values)]),
                             ['generated-secret-value', 'owner-secret-value', 'access-value-x', 'secret-value-x'])
            for path in (tmp / 'absent.env', tmp / 'private' / 'source.env'):
                with self.assertRaises(AssertionError):
                    collect_secrets([(path, env_secrets)])
            empty = tmp / 'empty.env'
            empty.write_text('# no credentials here\nPOSTGRES_DB=peertube\n')
            with self.assertRaises(AssertionError):
                collect_secrets([(empty, env_secrets)])


class StageRefusalTests(unittest.TestCase):
    """Refusals must arrive before the run leaves anything behind.

    Every attempt directory is permanent by design (results are never replaced),
    so a guard that fires after `out.mkdir()` burns an attempt label and leaves
    an empty directory that looks like an abandoned run; an export guard that
    fires after `out/` is populated leaves UNSCRUBBED evidence on disk.
    """

    def setUp(self):
        self.addCleanup(os.umask, os.umask(0o022))
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))

    def baseline(self, storage, tag='v0.6.5'):
        directory = self.tmp / 'baseline'
        directory.mkdir(exist_ok=True)
        (directory / 'candidate.json').write_text(json.dumps(
            {'tag': tag, 'assets': {f'vidra_{tag}_linux_amd64': {'sha256': 'a' * 64}}}))
        (directory / 'storage.json').write_text(json.dumps(storage))
        return directory

    def stage(self, preparation):
        directory = self.tmp / 'stage'
        directory.mkdir(exist_ok=True)
        (directory / 'preparation.json').write_text(json.dumps(preparation))
        return directory

    def prepared(self, **overrides):
        return {'status': 'PASS', 'source_container': 'vidra-v065-migration-source-20260914',
                'baseline': str(self.tmp / 'baseline'), 'candidate_tag': 'v0.6.5', **overrides}

    def refuse(self, baseline, preparation):
        stage = self.stage(preparation)
        with self.assertRaises(ValueError) as caught:
            execute(stage, 'reconcile', 'attempt-1', baseline, self.tmp / 'migration', self.tmp / 'key.json')
        self.assertFalse((stage / 'attempt-1').exists(), 'refusal burned an attempt label')
        return str(caught.exception)

    def test_local_storage_baseline_is_refused_before_the_attempt_directory(self):
        message = self.refuse(self.baseline({'backend': 'local'}), self.prepared())
        self.assertIn('B2', message)

    def test_stage_prepared_against_another_baseline_or_release_is_refused(self):
        baseline = self.baseline({'backend': 'b2', 'spec': B2_SPEC})
        self.assertIn('baseline', self.refuse(baseline, self.prepared(baseline='/root/vidra-v064-runtime')))
        self.assertIn('v0.6.4', self.refuse(baseline, self.prepared(candidate_tag='v0.6.4')))
        self.assertIn('source_container', self.refuse(baseline, self.prepared(source_container=None)))
        # Nonempty was the whole test before: a v0.6.4 clone left on the host
        # answers to `docker exec ... psql` exactly as a v0.6.5 one does, so a
        # recorded name from the previous drill reconciled the previous drill's
        # database and stamped the result v0.6.5.
        self.assertIn('source_container', self.refuse(baseline, self.prepared(
            source_container='vidra-v064-migration-source-20260911')))

    def continuation(self, **overrides):
        source = self.tmp / 'prior'
        source.mkdir(exist_ok=True)
        (source / 'preparation.json').write_text(json.dumps(
            self.prepared(status='FAIL', error='source role could write', **overrides)))
        return source

    def test_a_continuation_against_another_release_is_refused_before_anything_is_created(self):
        # `--prepared-source` re-supplies `--baseline` too, and the generated
        # PeerTube fixture hashes are IDENTICAL across releases, so nothing
        # further down prepare() would notice: a v0.6.5 drill continued with
        # `--prepared-source /root/vidra-v064-migration-20260911` reuses that
        # drill's container name and POSTGRES_PASSWORD and calls the evidence
        # v0.6.5. The stage's own record is the second opinion, and it is read
        # before the recorder, the clone or any host command exists.
        baseline = self.baseline({'backend': 'b2', 'spec': B2_SPEC})
        stage = self.tmp / 'continuation-stage'
        for bad in ({'candidate_tag': 'v0.6.4'}, {'baseline': '/root/vidra-v064-runtime'},
                    {'source_container': 'vidra-v064-migration-source-20260911'}):
            with self.subTest(bad=bad), patch('platform.machine', return_value='x86_64'), \
                    patch('platform.system', return_value='Linux'):
                with self.assertRaises(ValueError):
                    p.prepare(stage, baseline, self.continuation(**bad))
            self.assertFalse(stage.exists(), 'refusal created the stage it was asked to prepare')

    def test_a_stage_that_records_nothing_extra_is_still_accepted(self):
        # Legacy stages predate the recorded fields; only a DISAGREEING value is
        # a refusal, never a silent one.
        p.check_stage_prepared_for({'source_container': 'x'}, Path('/root/vidra-v065-runtime'), 'v0.6.5')
        p.check_stage_prepared_for(self.prepared(baseline='/b', candidate_tag='v0.6.5'), Path('/b'), 'v0.6.5')
        for bad in ({'baseline': '/other'}, {'candidate_tag': 'v0.6.4'}):
            with self.assertRaises(ValueError):
                p.check_stage_prepared_for(bad, Path('/b'), 'v0.6.5')


class ExportTopologyTests(unittest.TestCase):
    """A clean first-time PASS must be exportable.

    The v0.6.4 drill needed three prepare attempts, and the export hard-coded
    that shape: on a run that passes first time there is no `-continuation`
    stage, and the operator cannot manufacture one (`--prepared-source` is gated
    on the recorded read-only probe failure, and a same-day `docker run --name`
    collides). The export would have died on a missing file after every hour of
    host work was already spent.
    """

    def setUp(self):
        self.addCleanup(os.umask, os.umask(0o022))
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))
        self.root = self.tmp / 'vidra-v065-migration-20260914'

    def attempt(self, suffix=''):
        directory = Path(str(self.root) + suffix)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'preparation.json').write_text(json.dumps({'status': 'PASS'}))
        return directory

    def test_sources_follow_the_attempts_that_exist(self):
        first = self.attempt()
        self.assertEqual(export_tool.preparation_sources(self.root), [(first, 'prepare-original')])
        ready = self.attempt('-ready')
        self.assertEqual(export_tool.preparation_sources(self.root),
                         [(first, 'prepare-original'), (ready, 'prepare-ready')])
        continuation = self.attempt('-continuation')
        self.assertEqual(export_tool.preparation_sources(self.root),
                         [(first, 'prepare-original'), (continuation, 'prepare-continuation'),
                          (ready, 'prepare-ready')])

    def test_an_export_with_no_prepare_record_at_all_is_refused(self):
        self.root.mkdir(parents=True)
        with self.assertRaises(AssertionError) as caught:
            export_tool.preparation_sources(self.root)
        self.assertIn('nothing to export', str(caught.exception))

    def test_a_clean_first_time_prepare_exports_the_one_stage_that_exists(self):
        # Reaching the secret scan proved nothing once the scan moved ahead of
        # the topology: collect_secrets refuses first on any stage shape, so the
        # old assertion passed whether or not a missing `-continuation` would
        # still have raised FileNotFoundError. The scan is covered by
        # ExportSecretSourceTests; patching it out is what lets this test assert
        # the topology — that an export past the scan COMPLETES on a run with no
        # continuation, and records exactly the attempt that exists.
        self.attempt()
        with patch.object(export_tool, 'collect_secrets', return_value=['unrelated-secret']), \
                redirect_stdout(io.StringIO()):
            export_tool.export('reviewed', self.root, self.tmp / 'baseline', self.tmp / 'key.json')
        out = Path(str(self.root) + '-reviewed')
        provenance = json.loads((out / 'provenance.json').read_text())
        self.assertEqual(provenance['preparation_stages'], {'prepare-original': str(self.root)})
        self.assertEqual(provenance['secret_scan'], 'PASS')
        self.assertTrue((out / 'prepare-original.json').is_file())

    def test_a_refused_export_leaves_no_output_directory(self):
        self.attempt()
        out = Path(str(self.root) + '-reviewed')
        with self.assertRaises(AssertionError):
            export_tool.export('reviewed', self.root, self.tmp / 'baseline', self.tmp / 'key.json')
        self.assertFalse(out.exists(), 'refused export left an unscrubbed directory behind')
