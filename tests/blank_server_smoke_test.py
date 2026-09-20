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

    def test_meta_is_never_a_carry_over(self):
        # The bundle is built from meta AT the release tag, and every committed
        # manifest has meta there. Only the image-bearing components may lag.
        candidate = manifest('v0.7.5')
        candidate['repositories']['vidra']['tag'] = 'v0.1.0'
        with self.assertRaises(ValueError) as refused:
            p.validate_candidate(candidate)
        for fragment in ('vidra', 'v0.1.0', 'v0.7.5'):
            self.assertIn(fragment, str(refused.exception))

    def test_a_leading_zero_is_not_a_release_tag(self):
        # 'v0.07.3' is not the tag v0.7.3 and no such release exists; accepting
        # it would let a typo pass as a legitimate carry-over.
        for field, bad in (('tag', 'v0.07.3'), ('tag', 'v00.7.3')):
            with self.subTest(bad=bad):
                candidate = manifest('v0.7.5')
                candidate['repositories']['vidra-user'][field] = bad
                with self.assertRaises(ValueError) as refused:
                    p.validate_candidate(candidate)
                self.assertIn('vidra-user', str(refused.exception))

    def test_a_malformed_revision_is_a_named_refusal_not_a_crash(self):
        # A null revision used to raise TypeError out of re.fullmatch, which is
        # a harness bug to the reader, not a verdict on the manifest.
        for bad in (None, 42, ['a' * 40]):
            with self.subTest(revision=bad):
                candidate = manifest('v0.7.5')
                candidate['repositories']['vidra-user']['revision'] = bad
                with self.assertRaises(ValueError) as refused:
                    p.validate_candidate(candidate)
                self.assertIn('vidra-user', str(refused.exception))

    def test_carried_over_components_are_identical_to_their_own_release(self):
        # A carry-over must be the SAME artifact the older release recorded, not
        # merely an older-looking tag: compare the recorded source and image.
        for release in ('v0.7.4', 'v0.7.5'):
            candidate = manifest(release)
            carried = [repo for repo in p.COMPONENTS
                       if candidate['repositories'][repo]['tag'] != release]
            self.assertTrue(carried, f'{release} is expected to carry components forward')
            for repo in carried:
                tag = candidate['repositories'][repo]['tag']
                with self.subTest(release=release, repo=repo, tag=tag):
                    path = (Path(__file__).resolve().parents[1]
                            / f'docs/evidence/release-{tag}-verification/manifest.json')
                    # No skip: a carry-over whose own release has no committed
                    # manifest is unverifiable, which is a failure, not a pass.
                    self.assertTrue(path.exists(),
                                    f'{release} carries {repo} at {tag}, which has no committed manifest')
                    origin = manifest(tag)
                    self.assertEqual(candidate['repositories'][repo], origin['repositories'][repo])
                    self.assertEqual(candidate['images'][repo], origin['images'][repo])

    def test_expected_image_pins_each_component_at_its_own_tag(self):
        core_only = manifest('v0.7.5')
        self.assertEqual(p.expected_image(core_only, 'vidra-core'), 'ghcr.io/yegamble/vidra-core:v0.7.5')
        self.assertEqual(p.expected_image(core_only, 'vidra-user'), 'ghcr.io/yegamble/vidra-user:v0.7.3')
        self.assertEqual(p.expected_image(core_only, 'vidra-search'), 'ghcr.io/yegamble/vidra-search:v0.7.3')
        uniform = manifest('v0.6.6')
        for repo in p.COMPONENTS:
            self.assertEqual(p.expected_image(uniform, repo), f'ghcr.io/yegamble/{repo}:v0.6.6')

    def test_setup_pins_are_read_and_asserted_before_they_are_corrected(self):
        # Rewriting the pins without first reading them would silently absorb a
        # `setup --release-tag` that wrote the wrong tag — the runtime half of
        # the regression tests/install_test.sh guards for install.sh. setup
        # writes that ONE tag for all three services, so that is what A02 must
        # observe before correcting it for the core-only case.
        template = (Path(__file__).resolve().parents[1] / 'env/production.env.example').read_text()
        self.assertEqual(p.check_setup_pins(template, 'v0.7.3'),
                         {'VIDRA_CORE_TAG': 'v0.7.3', 'VIDRA_USER_TAG': 'v0.7.3',
                          'VIDRA_SEARCH_TAG': 'v0.7.3'})
        wrong = template.replace('VIDRA_SEARCH_TAG=v0.7.3', 'VIDRA_SEARCH_TAG=v0.6.6')
        with self.assertRaises(ValueError) as refused:
            p.check_setup_pins(wrong, 'v0.7.3')
        for fragment in ('VIDRA_SEARCH_TAG', 'v0.6.6', 'v0.7.3'):
            self.assertIn(fragment, str(refused.exception))
        missing = template.replace('VIDRA_USER_TAG=v0.7.3', '# VIDRA_USER_TAG removed')
        with self.assertRaises(ValueError) as absent:
            p.check_setup_pins(missing, 'v0.7.3')
        self.assertIn('VIDRA_USER_TAG', str(absent.exception))

    def test_the_env_temp_file_is_private_from_creation(self):
        # The env file carries secrets; it must never exist, even briefly, at
        # whatever mode the umask would have given it.
        previous = os.umask(0)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'production.env.tmp'
                p.write_private(path, 'VIDRA_CORE_TAG=v0.7.5\n')
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.read_text(), 'VIDRA_CORE_TAG=v0.7.5\n')
                # O_EXCL: a leftover temp file is a surprise, not a target.
                with self.assertRaises(FileExistsError):
                    p.write_private(path, 'x')
        finally:
            os.umask(previous)

    def test_pin_component_tags_rewrites_every_service_tag(self):
        template = (Path(__file__).resolve().parents[1] / 'env/production.env.example').read_text()
        pinned = p.pin_component_tags(template, manifest('v0.7.5'))
        for key, tag in (('VIDRA_CORE_TAG', 'v0.7.5'), ('VIDRA_USER_TAG', 'v0.7.3'),
                         ('VIDRA_SEARCH_TAG', 'v0.7.3')):
            self.assertIn(f'\n{key}={tag}\n', pinned)
        # A renamed or duplicated key must fail here, not leave the wrong pin.
        for broken in (template.replace('VIDRA_USER_TAG=', 'VIDRA_FRONTEND_TAG='),
                       template + '\nVIDRA_USER_TAG=v9.9.9\n'):
            with self.subTest(), self.assertRaises(ValueError):
                p.pin_component_tags(broken, manifest('v0.7.5'))

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
