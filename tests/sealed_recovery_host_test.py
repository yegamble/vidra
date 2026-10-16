"""Published archive/config boundaries without invoking Docker or a live host."""
import io
import hashlib
from pathlib import Path
import re
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import sealed_recovery_host as host


class FixtureHostBoundaryTest(unittest.TestCase):
    def test_failure_diagnostics_export_only_finite_service_states_and_http_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = host.Host(Path(temporary), {}, {})
            states = 'api\trestarting\t\nsearch\trunning\thealthy\nfrontend\trunning\tstarting\npostgres\texited\t\n'
            with patch.object(fixture, 'readyz_status', return_value=503), \
                    patch.object(fixture, 'run', return_value=states) as run:
                facts = fixture.failure_diagnostics()
            self.assertEqual(facts, {'readyz_status': 503, 'services': {'api': 'restarting', 'search': 'healthy',
                'frontend': 'starting', 'postgres': 'stopped', 'redis': 'missing'}})
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
            self.assertNotIn('inspect', run.call_args.args[0])
            self.assertNotIn('PRIVATE_CANARY', str(facts))

    def test_diagnostic_probe_failures_and_unrecognized_values_are_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = host.Host(Path(temporary), {}, {})
            for output in ('api\trunning\tPRIVATE_CANARY\n', 'PRIVATE_CANARY\trunning\thealthy\n',
                           'api\trunning\thealthy\napi\texited\t\n', 'PRIVATE_CANARY'):
                with self.subTest(output=output), patch.object(fixture, 'readyz_status', return_value=None), \
                        patch.object(fixture, 'run', return_value=output):
                    self.assertEqual(fixture.failure_diagnostics(), {'readyz_status': 0})
            with patch.object(fixture, 'readyz_status', side_effect=ValueError('PRIVATE_CANARY')), \
                    patch.object(fixture, 'run', side_effect=ValueError('PRIVATE_CANARY')):
                self.assertEqual(fixture.failure_diagnostics(), {})

    def test_authentic_zero_padded_bundle_schema_matches_integer_record(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            manifest = 'tag=v0.7.8\ncore_schema_version=0182\nmeta_commit=' + 'a' * 40 + '\ncore_commit=' + 'b' * 40
            for name, content in {'vidra-bundle.manifest': manifest, 'deploy/backup.sh': 'backup',
                                  'deploy/restore.sh': 'restore', 'deploy/lib.sh': 'lib'}.items():
                info = tarfile.TarInfo(name)
                data = content.encode()
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        assets = {'SHA256SUMS': b'fixture-sums', 'vidra-bundle_v0.7.8.tar.gz': stream.getvalue(),
                  'vidra_v0.7.8_linux_amd64': b'fixture-cli-not-executed'}
        candidate = {'assets': {name: {'url': 'https://fixture.invalid/' + name,
            'sha256': hashlib.sha256(data).hexdigest()} for name, data in assets.items()}}
        record = {'release': 'v0.7.8', 'meta_commit': 'a' * 40, 'core_schema_version': 182,
                  'components': {'core': {'commit': 'b' * 40}}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / 'stage'
            stage.mkdir()
            fixture = host.Host(stage, record, candidate)
            with patch.object(host, 'INSTALL', root / 'install'), patch.object(host.urllib.request, 'urlopen',
                    side_effect=lambda url, **_: io.BytesIO(assets[url.rsplit('/', 1)[-1]])):
                fixture.install()
            self.assertEqual(set(fixture.script_hashes), {'deploy/backup.sh', 'deploy/restore.sh', 'deploy/lib.sh'})

    def test_setup_generates_archivable_caddy_config_before_disabling_edge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage, install = root / 'stage', root / 'install'
            stage.mkdir()
            (install / 'env').mkdir(parents=True)
            (install / 'env/production.env').write_text('MFA_KEY_KEK=synthetic\n')
            fixture = host.Host(stage, {'release': 'v0.7.8', 'components': {}}, {})
            fixture.cli = root / 'fixture-cli'
            with patch.object(host, 'INSTALL', install), patch.object(fixture, 'run') as run:
                fixture.configure()
            command = run.call_args.args[0]
            self.assertEqual(command[command.index('--tls-mode') + 1], 'internal')
            self.assertIn('VIDRA_TLS_MODE=external\n', (install / 'env/production.env').read_text())

    def test_asset_hash_failure_leaves_install_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / 'stage'
            stage.mkdir()
            record = {'release': 'v0.7.8'}
            candidate = {'assets': {'SHA256SUMS': {'url': 'https://github.com/example', 'sha256': '0' * 64}}}
            fixture = host.Host(stage, record, candidate)
            self.assertNotIn('GITHUB_TOKEN', fixture.env)
            with patch.object(host, 'INSTALL', root / 'install'), \
                    patch.object(host.urllib.request, 'urlopen', return_value=io.BytesIO(b'bad checksum')):
                with self.assertRaises(ValueError):
                    fixture.install()
                self.assertFalse((root / 'install').exists())

    def test_setup_clears_scanner_address_from_actual_production_template(self):
        template = (Path(__file__).resolve().parents[1] / 'env/production.env.example').read_text()
        self.assertRegex(template, r'(?m)^CLAMAV_ADDR=clamav:3310$')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage, install = root / 'stage', root / 'install'
            stage.mkdir()
            (install / 'env').mkdir(parents=True)
            path = install / 'env/production.env'
            path.write_text(template)
            fixture = host.Host(stage, {'release': 'v0.7.8', 'components': {}}, {})
            fixture.cli = root / 'fixture-cli'
            with patch.object(host, 'INSTALL', install), patch.object(fixture, 'run'):
                fixture.configure()
            configured = dict(re.findall(r'(?m)^([A-Z][A-Z0-9_]*)=(.*)$', path.read_text()))
            self.assertEqual(configured['CLAMAV_ADDR'], '')
            self.assertEqual(configured['MALWARE_SCAN_MODE'], 'disabled')
            self.assertEqual(configured['VIDRA_COMPOSE_PROFILES'], 'core frontend')

    def test_untrusted_bundle_paths_and_links_never_extract(self):
        for name, kind in (('../outside', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('link', tarfile.SYMTYPE), ('pipe', tarfile.FIFOTYPE)):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                info = tarfile.TarInfo(name)
                info.type, info.linkname = kind, '/outside'
                archive.addfile(info)
            with tempfile.TemporaryDirectory() as temporary:
                bundle = Path(temporary) / 'bundle.tar.gz'
                bundle.write_bytes(stream.getvalue())
                with self.assertRaises(ValueError):
                    host.extract_bundle(bundle, Path(temporary) / 'installed')
                self.assertFalse((Path(temporary) / 'installed').exists())

    def test_controlled_settings_preserve_other_template_values(self):
        text = 'MFA_KEY_KEK=synthetic\nMAIL_ENABLED=true\n# MAIL_ENABLED=true\n'
        changed = host.set_values(text, {'MAIL_ENABLED': 'false', 'OAUTH_PROVIDERS': ''})
        self.assertIn('MFA_KEY_KEK=synthetic\n', changed)
        self.assertIn('MAIL_ENABLED=false\n', changed)
        self.assertIn('# MAIL_ENABLED=true\n', changed)
        self.assertTrue(changed.endswith('OAUTH_PROVIDERS=\n'))
        for text in ('MAIL_ENABLED=true\nMAIL_ENABLED=false\n',):
            with self.assertRaises(ValueError):
                host.set_values(text, {'MAIL_ENABLED': 'false'})
        with self.assertRaises(ValueError):
            host.set_values('', {'MAIL_ENABLED': 'false\nEXTERNAL=true'})

    def test_render_rejects_external_network_or_provider(self):
        api = {'VIDRA_ENV': 'production', 'STORAGE_BACKEND': 'local', 'MAIL_ENABLED': 'false',
               'OAUTH_PROVIDERS': '', 'FEDERATION_ENABLED': 'false', 'DEV_MAIL_CAPTURE_ENABLED': 'false',
               'CLAMAV_ADDR': '', 'MALWARE_SCAN_MODE': 'disabled'}
        model = {'networks': {'default': {'internal': True}}, 'services': {
            'api': {'environment': api, 'networks': {'default': {}}}}}
        host.check_isolation(model)
        for key, value in (('STORAGE_BACKEND', 's3'), ('MAIL_ENABLED', 'true'),
                           ('OAUTH_PROVIDERS', 'real'), ('FEDERATION_ENABLED', 'true'),
                           ('CLAMAV_ADDR', 'clamav:3310'), ('MALWARE_SCAN_MODE', 'fail-closed')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                host.check_isolation({**model, 'services': {'api': {
                    'environment': {**api, key: value}, 'networks': {'default': {}}}}})
        model['services']['api']['networks']['external'] = {}
        with self.assertRaises(ValueError):
            host.check_isolation(model)


if __name__ == '__main__':
    unittest.main()
