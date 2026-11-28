"""Keep the reference reporter exception narrow on both validation lanes."""

import copy
from pathlib import Path
import runpy
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ci/check-core-compose-consumers.py'
check = runpy.run_path(str(SCRIPT))['check']
KEY = 'IPFS_REFERENCE_STATUS_FILE'
SOURCE = '/tmp/reference-status'


class CoreComposeConsumersTest(unittest.TestCase):
    def setUp(self):
        self.base = {name: {'environment': {'SHARED_KEY': 'on'}} for name in ('api', 'worker')}
        self.enabled = copy.deepcopy(self.base)
        self.enabled['api']['environment'][KEY] = '/run/vidra-reference-status/status.json'
        self.enabled['api']['volumes'] = [{'type': 'bind', 'source': SOURCE,
                                         'target': '/run/vidra-reference-status', 'read_only': True,
                                         'bind': {'create_host_path': False}}]
        self.go_keys = {KEY, 'SHARED_KEY'}

    def test_shared_parity_and_real_reference_consumer(self):
        self.assertEqual(check(self.base, self.enabled, SOURCE, self.go_keys), 1)
        # A previous pinned core may predate the optional reader.
        self.assertEqual(check(self.base, self.enabled, SOURCE, {'SHARED_KEY'}), 1)
        with self.assertRaisesRegex(ValueError, 'UNWIRED'):
            check(self.base, self.enabled, SOURCE, self.go_keys | {'UNWIRED'})
        with self.assertRaisesRegex(ValueError, 'inventory is empty'):
            check(self.base, self.enabled, SOURCE, set())
        with self.assertRaisesRegex(ValueError, 'changed shared'):
            changed = copy.deepcopy(self.enabled)
            changed['worker']['environment']['ADDITIONAL'] = 'on'
            check(self.base, changed, SOURCE, self.go_keys)
        del self.base['worker']['environment']['SHARED_KEY']
        del self.enabled['worker']['environment']['SHARED_KEY']
        with self.assertRaisesRegex(ValueError, 'worker.*SHARED_KEY'):
            check(self.base, self.enabled, SOURCE, self.go_keys)

    def test_default_and_worker_reject_reference_exposure(self):
        for model, name in [(self.base, 'api'), (self.base, 'worker'), (self.enabled, 'worker')]:
            with self.subTest(name=name):
                model[name]['environment'][KEY] = ''
                with self.assertRaisesRegex(ValueError, 'unexpectedly exposes'):
                    check(self.base, self.enabled, SOURCE, self.go_keys)
                del model[name]['environment'][KEY]
                model[name]['volumes'] = [{'type': 'bind', 'source': SOURCE, 'target': '/elsewhere'}]
                with self.assertRaisesRegex(ValueError, 'unexpectedly exposes'):
                    check(self.base, self.enabled, SOURCE, self.go_keys)
                del model[name]['volumes']

    def test_playback_is_accounted_for_only_after_proving_the_api_mount(self):
        key = 'IPFS_REFERENCE_PLAYBACK_SOCKET'
        host = '/tmp/reference-playback'
        target = '/run/vidra-reference-playback'
        self.go_keys.add(key)
        with self.assertRaisesRegex(ValueError, 'enabled API'):
            check(self.base, self.enabled, SOURCE, self.go_keys, host)
        self.enabled['api']['environment'][key] = target + '/playback.sock'
        self.enabled['api']['volumes'].append({'type': 'bind', 'source': host, 'target': target, 'read_only': True})
        self.assertEqual(check(self.base, self.enabled, SOURCE, self.go_keys, host), 1)
        self.enabled['worker']['environment'][key] = target + '/playback.sock'
        with self.assertRaisesRegex(ValueError, 'worker unexpectedly exposes'):
            check(self.base, self.enabled, SOURCE, self.go_keys, host)
        del self.enabled['worker']['environment'][key]
        for exposed in (host, host + '/playback.sock', '/tmp'):
            with self.subTest(source=exposed):
                self.enabled['worker']['volumes'] = [
                    {'type': 'bind', 'source': exposed, 'target': '/different-path', 'read_only': True}]
                with self.assertRaisesRegex(ValueError, 'worker unexpectedly exposes'):
                    check(self.base, self.enabled, SOURCE, self.go_keys, host)

    def test_enabled_api_requires_exact_read_only_directory(self):
        bad = [([], '/run/vidra-reference-status/status.json'),
               (self.enabled['api']['volumes'], '/wrong/status.json')]
        for change in ({'type': 'volume'}, {'read_only': False}, {'source': '/other'},
                       {'target': '/other'}, {'bind': {'create_host_path': True}}):
            bad.append(([{**self.enabled['api']['volumes'][0], **change}],
                        '/run/vidra-reference-status/status.json'))
        for mounts, path in bad:
            with self.subTest(mounts=mounts, path=path):
                enabled = copy.deepcopy(self.enabled)
                enabled['api']['volumes'] = mounts
                enabled['api']['environment'][KEY] = path
                with self.assertRaisesRegex(ValueError, 'enabled API'):
                    check(self.base, enabled, SOURCE, self.go_keys)
