"""Acceptance must refuse misleading hosts, mutated inputs and wrong images."""
import copy
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import release_acceptance

from release_acceptance import check_host, execute, minimal_browser_lock, pin_images, prepare, verify_image, wait_for_health


ROOT = Path(__file__).resolve().parent.parent
CANDIDATE = json.loads((ROOT / 'docs/evidence/release-v0.6.4-verification/manifest.json').read_text())


class ReleaseAcceptanceTests(unittest.TestCase):
    def test_wrong_architecture_os_and_existing_data_are_refused(self):
        clean = {'system': 'Linux', 'architecture': 'x86_64', 'os': {'ID': 'ubuntu', 'VERSION_ID': '24.04'},
                 'root': True, 'systemd': True, 'container': False, 'existing': []}
        check_host(clean)
        for change in ({'architecture': 'aarch64'}, {'system': 'Darwin'}, {'root': False},
                       {'systemd': False}, {'container': True}, {'existing': ['/var/lib/docker']},
                       {'os': {'ID': 'ubuntu', 'VERSION_ID': '22.04'}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_host(dict(clean, **change))

    def test_pins_all_six_images_and_refuses_a_partial_mapping(self):
        source = (ROOT / 'docker-compose.prod.yml').read_text()
        pinned = pin_images(source, CANDIDATE)
        for repo, count in (('vidra-core', 3), ('vidra-user', 1), ('vidra-search', 2)):
            self.assertEqual(pinned.count('image: ' + CANDIDATE['images'][repo]['reference']), count)
        self.assertEqual(pinned.count('platform: linux/amd64'), 6)
        # A changed overlay must not silently leave even one service on a tag.
        with self.assertRaises(ValueError):
            pin_images(re.sub(r'(image: \S*)/vidra-core:', r'\1/unexpected-core:', source, count=1), CANDIDATE)
        with self.assertRaises(ValueError):
            pin_images(pinned, CANDIDATE)

    def test_running_image_must_match_digest_id_revision_and_platform(self):
        expected = CANDIDATE['images']['vidra-core']
        info = {'Id': 'sha256:config-id', 'RepoDigests': [expected['reference']], 'Os': 'linux',
                'Architecture': 'amd64', 'Config': {'Labels': {'org.opencontainers.image.revision': expected['revision']}}}
        container = {'Image': info['Id'], 'Config': {'Image': expected['reference']}}
        verify_image(info, expected, container)
        for field, value in (('RepoDigests', []), ('Architecture', 'arm64'), ('Id', 'other'),
                             ('Config', {'Labels': None}),
                             ('Config', {'Labels': {'org.opencontainers.image.revision': 'new-build'}})):
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_image(dict(info, **{field: value}), expected, container)
        with self.assertRaises(ValueError):
            verify_image(info, expected, {'Image': info['Id'], 'Config': {'Image': 'ghcr.io/yegamble/vidra-core:v0.6.4'}})

    def test_browser_lock_keeps_integrities_and_rejects_unknown_dependencies(self):
        packages = {}
        for name, deps in (('@playwright/test', {'playwright': '1.63.0'}),
                           ('playwright', {'playwright-core': '1.63.0'}), ('playwright-core', {})):
            packages['node_modules/' + name] = {'version': '1.63.0', 'devOptional': True,
                'resolved': 'https://registry.npmjs.org/example.tgz', 'integrity': 'sha512-original', 'dependencies': deps}
        package, lock = minimal_browser_lock({'packages': packages})
        self.assertEqual(package['dependencies'], {'@playwright/test': '1.63.0'})
        self.assertEqual(lock['packages']['node_modules/playwright']['integrity'], 'sha512-original')
        bad = copy.deepcopy(packages)
        bad['node_modules/playwright']['optionalDependencies'] = {'surprise': '1.0.0'}
        with self.assertRaises(ValueError):
            minimal_browser_lock({'packages': bad})

    def test_mutated_handoff_fails_before_host_or_install_mutation_and_retains_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / 'install.sh').write_text('changed')
            (stage / 'handoff.json').write_text(json.dumps({'files': {'install.sh': 'wrong-hash'}}))
            self.assertEqual(execute(stage, 'fresh-disposable-host'), 1)
            evidence = json.loads((stage / 'result.json').read_text())
            self.assertEqual(evidence['status'], 'FAIL')
            self.assertEqual(evidence['candidate_certification'], 'NOT_ESTABLISHED')
            self.assertIn('handoff file changed', evidence['error'])
            self.assertFalse((stage / 'private').exists())
            with self.assertRaises(ValueError):
                execute(stage, 'fresh-disposable-host')

    def test_acknowledgement_required_before_any_output(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                execute(Path(directory), 'existing-shared-lab')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_health_waits_for_first_docker_probe_after_http_is_ready(self):
        observations = iter([{'frontend': 'starting', 'api': 'healthy'},
                             {'frontend': 'healthy', 'api': 'healthy'}])
        pauses = []
        self.assertEqual(wait_for_health(lambda: next(observations), clock=lambda: 0,
                                         pause=pauses.append)['frontend'], 'healthy')
        self.assertEqual(pauses, [2])

    def test_health_timeout_and_empty_observations_cannot_pass(self):
        ticks = iter([0, 0, 2])
        with self.assertRaisesRegex(ValueError, 'runtime health timeout'):
            wait_for_health(lambda: {'frontend': 'unhealthy'}, timeout=1,
                            clock=lambda: next(ticks), pause=lambda seconds: None)
        with self.assertRaisesRegex(ValueError, 'no running-service'):
            wait_for_health(lambda: {}, clock=lambda: 0)



class CandidateSelectionTests(unittest.TestCase):
    """The harness must not silently adopt a candidate other than the one whose
    frozen evidence directory it was pointed at — nor run a handoff prepared
    for another release."""

    def test_prepare_refuses_a_manifest_whose_tag_disagrees_with_its_evidence_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence = base / 'docs/evidence/release-v0.6.5-verification'
            evidence.mkdir(parents=True)
            (evidence / 'manifest.json').write_text(json.dumps(CANDIDATE))  # a v0.6.4 manifest under a v0.6.5 directory
            with patch.object(release_acceptance, 'ROOT', base), self.assertRaises(ValueError) as refused:
                prepare(base / 'frozen', base / 'out', base / 'node.tar.xz', base / 'sums.txt',
                        candidate_path=evidence / 'manifest.json')
            self.assertIn('wrong frozen candidate', str(refused.exception))
            self.assertFalse((base / 'out').exists())

    def test_prepare_accepts_a_manifest_that_matches_its_evidence_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            evidence = base / 'docs/evidence/release-v0.6.5-verification'
            evidence.mkdir(parents=True)
            manifest = copy.deepcopy(CANDIDATE)
            manifest['tag'] = 'v0.6.5'
            for source in manifest['repositories'].values():
                source['tag'] = 'v0.6.5'  # validate_candidate requires every repository to carry the manifest's tag
            (evidence / 'manifest.json').write_text(json.dumps(manifest))
            with patch.object(release_acceptance, 'ROOT', base), self.assertRaises(subprocess.CalledProcessError) as later:
                prepare(base / 'frozen', base / 'out', base / 'node.tar.xz', base / 'sums.txt',
                        candidate_path=evidence / 'manifest.json')
            # The candidate guard passed; the failure is the absent frozen tree, not the tag.
            self.assertNotIn('wrong frozen candidate', str(later.exception))

    def test_run_refuses_a_handoff_prepared_for_another_release(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / 'candidate.json').write_text(json.dumps(CANDIDATE))  # tag v0.6.4
            import hashlib
            digest = hashlib.sha256((stage / 'candidate.json').read_bytes()).hexdigest()
            (stage / 'handoff.json').write_text(json.dumps({'files': {'candidate.json': digest}, 'candidate_tag': 'v0.6.5'}))
            self.assertEqual(execute(stage, 'fresh-disposable-host'), 1)
            evidence = json.loads((stage / 'result.json').read_text())
            self.assertEqual(evidence['status'], 'FAIL')
            self.assertIn('wrong candidate', evidence['error'])

    def test_prepare_refuses_a_manifest_outside_the_committed_evidence_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            elsewhere = base / 'scratch/release-v0.6.5-verification'
            elsewhere.mkdir(parents=True)
            manifest = copy.deepcopy(CANDIDATE)
            manifest['tag'] = 'v0.6.5'
            for source in manifest['repositories'].values():
                source['tag'] = 'v0.6.5'
            (elsewhere / 'manifest.json').write_text(json.dumps(manifest))
            with patch.object(release_acceptance, 'ROOT', base), self.assertRaises(ValueError) as refused:
                prepare(base / 'frozen', base / 'out', base / 'node.tar.xz', base / 'sums.txt',
                        candidate_path=elsewhere / 'manifest.json')
            self.assertIn('committed evidence record', str(refused.exception))

    def test_run_refuses_a_handoff_that_does_not_hash_the_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / 'candidate.json').write_text(json.dumps(CANDIDATE))
            (stage / 'handoff.json').write_text(json.dumps({'files': {}, 'candidate_tag': 'v0.6.4'}))
            self.assertEqual(execute(stage, 'fresh-disposable-host'), 1)
            evidence = json.loads((stage / 'result.json').read_text())
            self.assertIn('handoff does not cover candidate.json', evidence['error'])

    def test_run_refuses_a_legacy_handoff_without_a_candidate_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / 'candidate.json').write_text(json.dumps(CANDIDATE))
            import hashlib
            digest = hashlib.sha256((stage / 'candidate.json').read_bytes()).hexdigest()
            (stage / 'handoff.json').write_text(json.dumps({'files': {'candidate.json': digest}}))
            self.assertEqual(execute(stage, 'fresh-disposable-host'), 1)
            self.assertIn('wrong candidate', json.loads((stage / 'result.json').read_text())['error'])


if __name__ == '__main__':
    unittest.main()
