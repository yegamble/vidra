"""Published archive/config boundaries without invoking Docker or a live host."""
import io
import hashlib
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import sealed_recovery_host as host


class FixtureHostBoundaryTest(unittest.TestCase):
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
               'OAUTH_PROVIDERS': '', 'FEDERATION_ENABLED': 'false', 'DEV_MAIL_CAPTURE_ENABLED': 'false'}
        model = {'networks': {'default': {'internal': True}}, 'services': {
            'api': {'environment': api, 'networks': {'default': {}}}}}
        host.check_isolation(model)
        for key, value in (('STORAGE_BACKEND', 's3'), ('MAIL_ENABLED', 'true'),
                           ('OAUTH_PROVIDERS', 'real'), ('FEDERATION_ENABLED', 'true')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                host.check_isolation({**model, 'services': {'api': {
                    'environment': {**api, key: value}, 'networks': {'default': {}}}}})
        model['services']['api']['networks']['external'] = {}
        with self.assertRaises(ValueError):
            host.check_isolation(model)


if __name__ == '__main__':
    unittest.main()
