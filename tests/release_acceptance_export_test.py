"""The export helper's path derivation: the stage is argv[1], the B2 completion stage argv[2]."""
from pathlib import Path
import unittest

from release_acceptance_export import paths


class ExportPathsTests(unittest.TestCase):
    def test_default_is_the_v064_runtime_stage(self):
        stage, completion, out, archive, key = paths(['x'])
        self.assertEqual(stage, Path('/root/vidra-v064-runtime'))
        self.assertIsNone(completion)
        self.assertEqual(out, Path('/root/vidra-v064-reviewed-evidence'))
        self.assertEqual(archive, Path('/root/vidra-v064-reviewed-evidence.tar.gz'))
        self.assertEqual(key, Path('/root/vidra-v064-b2-key.json'))

    def test_stage_argument_does_not_become_the_completion_stage(self):
        stage, completion, out, archive, key = paths(['x', '/root/vidra-v065-runtime'])
        self.assertEqual(stage, Path('/root/vidra-v065-runtime'))
        self.assertIsNone(completion)
        self.assertEqual(out, Path('/root/vidra-v065-reviewed-evidence'))
        self.assertEqual(archive, Path('/root/vidra-v065-reviewed-evidence.tar.gz'))
        self.assertEqual(key, Path('/root/vidra-v065-b2-key.json'))

    def test_completion_stage_is_the_second_argument(self):
        stage, completion, *_ = paths(['x', '/root/vidra-v064-runtime', '/root/vidra-v064-b2-completion'])
        self.assertEqual(completion, Path('/root/vidra-v064-b2-completion'))

    def test_non_runtime_stage_name_is_refused(self):
        with self.assertRaises(AssertionError):
            paths(['x', '/root/vidra-v064-b2-completion'])


if __name__ == '__main__':
    unittest.main()
