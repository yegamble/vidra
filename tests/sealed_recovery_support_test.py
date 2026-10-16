"""Pure boundary tests; no external account, host or image is used."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sealed_support', ROOT / 'tests/sealed_recovery_support.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class PublishedBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.record = json.loads((ROOT / 'releases/v0.7.7.json').read_text())
        self.manifest = json.loads((ROOT / self.record['evidence']).read_text())
        (self.root / 'releases').mkdir()
        self.path = self.root / 'releases/v0.7.7.json'
        self.path.write_text(json.dumps(self.record))
        evidence = self.root / self.record['evidence']
        evidence.parent.mkdir(parents=True)
        evidence.write_text(json.dumps(self.manifest))

    def load(self):
        with patch.object(support, 'head', return_value='a' * 40):
            return support.published(self.root, 'v0.7.7', 'a' * 40)

    def test_exact_record_and_platform_digest_are_required(self):
        record, candidate = self.load()
        for role in ('core', 'user', 'search'):
            self.assertEqual(candidate['images']['vidra-' + role]['digest'],
                             record['components'][role]['image']['platforms']['linux/amd64'])
        with patch.object(support, 'head', return_value='b' * 40), self.assertRaises(ValueError):
            support.published(self.root, 'v0.7.7', 'a' * 40)
        for revision in ('main', 'a' * 39, ''):
            with self.assertRaises(ValueError):
                support.published(self.root, 'v0.7.7', revision)

    def test_manifest_cannot_substitute_other_source_or_image(self):
        for field in ('revision', 'digest'):
            manifest = copy.deepcopy(self.manifest)
            manifest['images']['vidra-core'][field] = 'a' * 40 if field == 'revision' else 'sha256:' + '0' * 64
            (self.root / self.record['evidence']).write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                self.load()

    def test_provenance_or_external_evidence_path_is_refused(self):
        for key, value in (('meta_commit', '0' * 40), ('evidence', '../manifest.json')):
            record = {**self.record, key: value}
            self.path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                self.load()


class HandoffBoundaryTest(unittest.TestCase):
    def archive(self, names):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name in names:
                info = tarfile.TarInfo(name)
                info.size = 1
                archive.addfile(info, io.BytesIO(b'x'))
        return stream.getvalue()

    def test_only_exact_fixed_members_are_accepted(self):
        good = self.archive(support.MEMBERS)
        self.assertEqual(set(support.inspect_handoff(good)), support.MEMBERS)
        for names in (support.MEMBERS | {'.env'}, support.MEMBERS - {'proof.json'},
                      support.MEMBERS | {'../token'}, list(support.MEMBERS) + ['proof.json']):
            with self.assertRaises(ValueError):
                support.inspect_handoff(self.archive(names))

    def test_symlink_and_oversized_member_are_refused(self):
        for kind, size in ((tarfile.SYMTYPE, 0), (tarfile.REGTYPE, support.MAX_HANDOFF + 1)):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as archive:
                info = tarfile.TarInfo('proof.json')
                info.type, info.size, info.linkname = kind, size, '/tmp/token'
                archive.addfile(info)
            with self.assertRaises(ValueError):
                support.inspect_handoff(stream.getvalue())

    def test_preinstalled_docker_is_not_an_existing_vidra_deployment(self):
        facts = {'system': 'Linux', 'architecture': 'x86_64', 'os': {'ID': 'ubuntu', 'VERSION_ID': '24.04'},
                 'root': True, 'systemd': True, 'container': False,
                 'existing': ['/var/lib/docker', '/etc/docker', 'docker', 'containerd']}
        support.check_vm(facts, 'new-boot', 'old-boot')
        for changed in ({'existing': ['vidra']}, {'container': True}, {'root': False}):
            with self.assertRaises(ValueError):
                support.check_vm({**facts, **changed}, 'new-boot', 'old-boot')
        with self.assertRaises(ValueError):
            support.check_vm(facts, 'same-boot', 'same-boot')


if __name__ == '__main__':
    unittest.main()
