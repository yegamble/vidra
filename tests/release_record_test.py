"""deploy/release-record.py: the testable seam deploy/release.sh uses to write
releases/<tag>.json itself, closing finding #189 (records were produced out of
band, so the script that cut the tag never wrote the record that names the tag's
image digests).

The seam splits the record the way a release is actually cut: a digest-less
SKELETON built from what is known before the images exist (tags, source commits,
schema versions), then FINALIZED with the index/platform digests the GHCR
verification resolves after publish. release.sh does both locally and commits the
FINALIZED record — the completed record must satisfy the very same
deploy/release-mapping.py the deploy and rollback paths run, or a record the
script writes would be one the checker refuses. That equivalence is the point of
these tests: they build both halves and hold the finished record against the real
validator, so the two cannot drift.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SEAM = ROOT / 'deploy/release-record.py'
CHECKER = ROOT / 'deploy/release-mapping.py'


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rr = _load(SEAM, 'release_record')
mapping = _load(CHECKER, 'release_mapping')

TAG = 'v0.6.6'
# A source commit per component and the meta commit the tag points at.
COMMITS = {'core': 'a' * 40, 'user': 'b' * 40, 'search': 'c' * 40}
META_COMMIT = 'd' * 40
# `docker buildx imagetools inspect <ref> --format '{{json .Manifest}}'` for a
# multi-arch image: the index descriptor's own digest, its per-platform child
# manifests, and the buildx attestation manifest that must NOT become a platform.
INDEX = {'core': 'sha256:' + '1' * 64, 'user': 'sha256:' + '2' * 64, 'search': 'sha256:' + '3' * 64}
AMD64 = {'core': 'sha256:' + '4' * 64, 'user': 'sha256:' + '5' * 64, 'search': 'sha256:' + '6' * 64}


def manifest_json(component):
    return json.dumps({
        'mediaType': 'application/vnd.oci.image.index.v1+json',
        'digest': INDEX[component],
        'manifests': [
            {'mediaType': 'application/vnd.oci.image.manifest.v1+json',
             'digest': AMD64[component], 'platform': {'os': 'linux', 'architecture': 'amd64'}},
            {'mediaType': 'application/vnd.oci.image.manifest.v1+json',
             'digest': 'sha256:' + '7' * 64, 'platform': {'os': 'unknown', 'architecture': 'unknown'},
             'annotations': {'vnd.docker.reference.type': 'attestation-manifest'}},
        ],
    })


def a_skeleton():
    return rr.build_skeleton(
        release=TAG, meta_commit=META_COMMIT,
        core_schema_version='146', search_schema_version='18',
        components={
            'core': {'tag': TAG, 'commit': COMMITS['core'], 'repository': 'ghcr.io/yegamble/vidra-core'},
            'user': {'tag': TAG, 'commit': COMMITS['user'], 'repository': 'ghcr.io/yegamble/vidra-user'},
            'search': {'tag': TAG, 'commit': COMMITS['search'], 'repository': 'ghcr.io/yegamble/vidra-search'},
        },
        evidence=f'docs/evidence/release-{TAG}-verification/manifest.json')


def digests_from_manifests():
    return {c: rr.parse_manifest(manifest_json(c)) for c in ('core', 'user', 'search')}


class SkeletonTests(unittest.TestCase):
    def test_skeleton_is_schema_1_with_the_pre_publish_facts_and_no_digests(self):
        skel = a_skeleton()
        self.assertEqual(skel['schema_version'], 1)
        self.assertEqual(skel['release'], TAG)
        self.assertEqual(skel['meta_commit'], META_COMMIT)
        # schema versions are integers even though they arrive as CLI strings
        self.assertEqual(skel['core_schema_version'], 146)
        self.assertEqual(skel['search_schema_version'], 18)
        self.assertIsInstance(skel['core_schema_version'], int)
        for name in ('core', 'user', 'search'):
            image = skel['components'][name]['image']
            self.assertEqual(skel['components'][name]['tag'], TAG)
            self.assertEqual(skel['components'][name]['commit'], COMMITS[name])
            self.assertTrue(image['repository'].endswith('/vidra-' + name))
            # no digests yet: the images do not exist when the skeleton is built
            self.assertIsNone(image['index_digest'])
            self.assertEqual(image['platforms'], {})
        self.assertTrue(rr.is_skeleton(skel))

    def test_a_skeleton_carries_no_digest_string_anywhere(self):
        blob = json.dumps(a_skeleton())
        self.assertNotIn('sha256:', blob)


class ParseManifestTests(unittest.TestCase):
    def test_index_digest_and_only_real_platforms(self):
        index, platforms = rr.parse_manifest(manifest_json('core'))
        self.assertEqual(index, INDEX['core'])
        # the attestation manifest (unknown/unknown) must not become a platform
        self.assertEqual(platforms, {'linux/amd64': AMD64['core']})

    def test_a_missing_index_digest_is_refused(self):
        with self.assertRaises(ValueError):
            rr.parse_manifest(json.dumps({'manifests': []}))

    def test_no_real_platform_is_refused(self):
        only_attestation = json.dumps({'digest': INDEX['core'], 'manifests': [
            {'digest': 'sha256:' + '7' * 64, 'platform': {'os': 'unknown', 'architecture': 'unknown'}}]})
        with self.assertRaises(ValueError):
            rr.parse_manifest(only_attestation)


class FinalizeTests(unittest.TestCase):
    def test_finalize_fills_every_digest_and_leaves_the_facts_intact(self):
        skel = a_skeleton()
        record = rr.finalize(skel, digests_from_manifests())
        self.assertFalse(rr.is_skeleton(record))
        for name in ('core', 'user', 'search'):
            image = record['components'][name]['image']
            self.assertEqual(image['index_digest'], INDEX[name])
            self.assertEqual(image['platforms'], {'linux/amd64': AMD64[name]})
            # the pre-publish facts are untouched by finalize
            self.assertEqual(record['components'][name]['commit'], COMMITS[name])
        # finalize must not mutate its input skeleton
        self.assertTrue(rr.is_skeleton(skel))

    def test_finalize_refuses_a_non_skeleton(self):
        already = rr.finalize(a_skeleton(), digests_from_manifests())
        with self.assertRaises(ValueError):
            rr.finalize(already, digests_from_manifests())

    def test_finalize_refuses_a_missing_component_digest(self):
        partial = digests_from_manifests()
        del partial['search']
        with self.assertRaises((ValueError, KeyError)):
            rr.finalize(a_skeleton(), partial)


class ValidatorEquivalenceTests(unittest.TestCase):
    """The completed record must pass the exact validator the deploy/rollback
    paths run — a record release.sh writes that release-mapping.py would refuse is
    a record that stops a deploy."""

    def _validate(self, record):
        path = Path(f'/records/{record["release"]}.json')  # only .name/.parent are read
        result = mapping.validate(path, record)
        # validate() historically returned a list of problems; the seam work adds
        # a skeleton flag. Accept either shape so this test pins behaviour, not form.
        problems = result[0] if isinstance(result, tuple) else result
        return problems

    def test_completed_record_has_no_validation_problems(self):
        record = rr.finalize(a_skeleton(), digests_from_manifests())
        self.assertEqual(self._validate(record), [])

    def test_completed_record_passes_the_checker_cli_as_a_paired_deploy(self):
        record = rr.finalize(a_skeleton(), digests_from_manifests())
        with tempfile.TemporaryDirectory() as tmp:
            releases = Path(tmp) / 'releases'
            releases.mkdir()
            (releases / f'{TAG}.json').write_text(json.dumps(record, indent=2))
            env = Path(tmp) / 'production.env'
            env.write_text(f'VIDRA_CORE_TAG={TAG}\nVIDRA_USER_TAG={TAG}\nVIDRA_SEARCH_TAG={TAG}\n')
            result = subprocess.run(
                ['python3', str(CHECKER), 'check', '--mode', 'deploy',
                 '--releases', str(releases), '--env', str(env)],
                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
