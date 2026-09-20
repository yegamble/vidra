"""A02 assertions must reject incomplete or misleading host evidence."""
import copy
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('smoke', Path(__file__).with_name('blank_server_smoke.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def manifest(tag):
    """The committed preflight manifest of a real release — never a stub: the
    shapes under test here are the ones the harness is actually handed."""
    return json.loads((Path(__file__).resolve().parents[1]
                       / f'docs/evidence/release-{tag}-verification/manifest.json').read_text())


class SmokeTests(unittest.TestCase):
    def candidate(self):
        return json.loads((Path(__file__).resolve().parents[1] / 'docs/evidence/a01-v0.6.2-linux-amd64.json').read_text())

    def test_only_complete_a01_candidate_can_create_vm(self):
        candidate = self.candidate()
        p.validate_candidate(candidate)
        for field in ('repositories', 'images', 'assets', 'checks'):
            bad = copy.deepcopy(candidate)
            bad[field] = {}
            with self.assertRaises(ValueError):
                p.validate_candidate(bad)
        candidate['status'] = 'UNVERIFIED'
        with self.assertRaises(ValueError):
            p.validate_candidate(candidate)

    def test_moving_image_tag_is_rejected(self):
        candidate = self.candidate()
        candidate['images']['vidra-core']['reference'] = 'ghcr.io/yegamble/vidra-core:latest'
        with self.assertRaises(ValueError):
            p.validate_candidate(candidate)

    def model(self):
        return {'services': {**{name: {} for name in ('postgres', 'redis', 'search')},
            'api': {'ports': [{'host_ip': '127.0.0.1', 'target': 8080, 'published': '8080'}]},
            'frontend': {'ports': [{'host_ip': '127.0.0.1', 'target': 3000, 'published': '3000'}]}}}

    def test_exact_loopback_ports_and_no_datastore_publication(self):
        p.check_ports(self.model())
        for name in ('postgres', 'redis', 'search'):
            model = self.model()
            model['services'][name]['ports'] = [{'host_ip': '0.0.0.0', 'target': 5432}]
            with self.assertRaises(ValueError):
                p.check_ports(model)
        for name in ('api', 'frontend'):
            model = self.model()
            model['services'][name]['ports'][0].pop('host_ip')
            with self.assertRaises(ValueError):
                p.check_ports(model)

    def test_empty_profile_render_cannot_pass(self):
        with self.assertRaises(ValueError):
            p.check_ports({'services': {}})
        model = self.model()
        model['services']['api']['ports'] = []
        with self.assertRaises(ValueError):
            p.check_ports(model)

    def test_native_cli_checksum_is_selected_exactly_once(self):
        sums = 'a' * 64 + '  vidra_v0.6.2_linux_arm64\n' + 'b' * 64 + '  vidra_v0.6.2_linux_amd64\n'
        self.assertEqual(p.expected_hash(sums, 'vidra_v0.6.2_linux_arm64'), 'a' * 64)
        for text in ('', sums + sums):
            with self.assertRaises(ValueError):
                p.expected_hash(text, 'vidra_v0.6.2_linux_arm64')

    def test_component_tag_equal_to_the_release_is_still_accepted(self):
        # v0.6.6 moved all three components together; the looser structural rule
        # must not turn the ordinary uniform release into a special case.
        p.validate_candidate(manifest('v0.6.6'))

    def test_existing_output_refused_before_any_vm_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / 'multipass-called'
            tool = root / 'multipass'
            tool.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 99\n')
            tool.chmod(0o755)
            candidate = root / 'candidate.json'
            candidate.write_text(json.dumps(self.candidate()))
            script = Path(__file__).with_name('blank-server-smoke.sh')
            result = subprocess.run(['bash', str(script), str(candidate), tmp],
                env=dict(os.environ, PATH=str(root) + ':' + os.environ['PATH']),
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('output exists', result.stderr)
            self.assertFalse(marker.exists())


class ComponentTagTests(unittest.TestCase):
    """A core-only release is a legitimate manifest, not a malformed one.

    v0.7.4 and v0.7.5 ship vidra-core alone; vidra-user and vidra-search stay
    pinned at the v0.7.3 they were last cut at. Requiring every component tag to
    EQUAL the release tag refused both manifests outright, which gated the
    runtime, B2, migration and recovery lanes on every consumer of
    `validate_candidate`. What must still be refused is a component ahead of the
    release that claims to contain it, a tag that is not a release tag, and a
    "release" that shipped nothing.
    """

    def retagged(self, candidate, release):
        # Assets are named and linked after the release, so a bare tag swap
        # would trip the asset checks instead of the tag comparison under test.
        old = candidate['tag']
        candidate = copy.deepcopy(candidate)
        candidate['tag'] = release
        candidate['assets'] = {name.replace(old, release): dict(asset, url=asset['url'].replace(old, release))
                               for name, asset in candidate['assets'].items()}
        for source in candidate['repositories'].values():
            if source['tag'] == old:
                source['tag'] = release
        return candidate

    def test_committed_core_only_manifests_validate(self):
        for tag in ('v0.7.4', 'v0.7.5'):
            with self.subTest(tag=tag):
                candidate = manifest(tag)
                self.assertEqual(candidate['repositories']['vidra-core']['tag'], tag)
                self.assertEqual({candidate['repositories'][repo]['tag']
                                  for repo in ('vidra-user', 'vidra-search')}, {'v0.7.3'})
                p.validate_candidate(candidate)

    def test_a_component_newer_than_the_release_is_refused(self):
        candidate = manifest('v0.7.5')
        candidate['repositories']['vidra-user']['tag'] = 'v0.8.0'
        with self.assertRaises(ValueError) as refused:
            p.validate_candidate(candidate)
        # The message must name the repository, its tag and the release, or the
        # operator cannot tell a core-only release from a mispaired manifest.
        for fragment in ('vidra-user', 'v0.8.0', 'v0.7.5'):
            self.assertIn(fragment, str(refused.exception))

    def test_a_release_no_component_carries_is_refused(self):
        candidate = manifest('v0.7.5')
        candidate['repositories']['vidra-core']['tag'] = 'v0.7.3'
        with self.assertRaises(ValueError) as refused:
            p.validate_candidate(candidate)
        self.assertIn('v0.7.5', str(refused.exception))

    def test_a_component_tag_that_is_not_a_release_tag_is_refused(self):
        for bad in ('v0.7.3-rc1', 'latest', 'v0.7', '0.7.3', ''):
            with self.subTest(tag=bad):
                candidate = manifest('v0.7.5')
                candidate['repositories']['vidra-search']['tag'] = bad
                with self.assertRaises(ValueError) as refused:
                    p.validate_candidate(candidate)
                self.assertIn('vidra-search', str(refused.exception))
                self.assertIn('v0.7.5', str(refused.exception))

    def test_component_tags_are_ordered_numerically_not_lexically(self):
        # 'v0.7.10' sorts BELOW 'v0.7.9' as a string and ABOVE it as a release.
        # A string comparison gets both of these cases exactly backwards.
        release = self.retagged(manifest('v0.7.5'), 'v0.7.10')
        p.validate_candidate(release)
        older = copy.deepcopy(release)
        older['repositories']['vidra-user']['tag'] = 'v0.7.9'
        p.validate_candidate(older)
        newer = manifest('v0.7.5')
        newer['repositories']['vidra-user']['tag'] = 'v0.7.10'
        with self.assertRaises(ValueError):
            p.validate_candidate(newer)


if __name__ == '__main__':
    unittest.main()
