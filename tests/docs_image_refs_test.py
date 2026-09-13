"""No runbook, recipe or deploy file points at a MinIO image that no longer resolves.

Docker Hub's `minio/minio` repository is gone and the gcr mirror of it 404s
too, so every lab recipe that said "start MinIO from Docker Hub" now fails at
`docker pull`, on the machine being rehearsed, with the acceptance record
open beside it. vidra-core pins the image from quay.io by digest
(backend-integration.yml); the prose here must say the same, or the next
operator reproducing an A24/A33/A34 lab copies a command that cannot run.

Tracked files under docs/**/*.md, deploy/, env/ and docker-compose*.yml are
scanned. The evidence JSON under docs/evidence/ is deliberately NOT: it
records what was actually run at the time, and rewriting it would be
rewriting history. Nothing here skips: `git ls-files` failing fails the test.
"""
from pathlib import Path
import re
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
# `minio/minio` not preceded by `quay.io/` (docker.io/minio/minio and a bare
# minio/minio are both Docker Hub), and any use of the gcr mirror's minio path.
DOCKER_HUB_MINIO = re.compile(r'(?<!quay\.io/)\bminio/minio\b')
GCR_MIRROR_MINIO = re.compile(r'mirror\.gcr\.io/minio\b')
PATHSPECS = ['docs/*.md', 'docs/**/*.md', 'deploy', 'env', 'docker-compose*.yml']


def tracked_files():
    out = subprocess.run(['git', 'ls-files', '--', *PATHSPECS], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    return sorted(set(line for line in out.splitlines() if line))


class DocsImageRefsTests(unittest.TestCase):
    def test_the_scan_covers_the_runbook(self):
        files = tracked_files()
        self.assertIn('docs/release-readiness.md', files)
        self.assertTrue(any(f.startswith('deploy/') for f in files))
        self.assertIn('docker-compose.yml', files)

    def test_no_docker_hub_or_gcr_mirror_minio_references(self):
        offenders = []
        for rel in tracked_files():
            text = (REPO / rel).read_text(encoding='utf-8', errors='replace')
            for lineno, line in enumerate(text.splitlines(), 1):
                if DOCKER_HUB_MINIO.search(line) or GCR_MIRROR_MINIO.search(line):
                    offenders.append(f'{rel}:{lineno}: {line.strip()[:120]}')
        self.assertEqual(offenders, [], 'MinIO image references that no longer resolve '
                         '(use quay.io/minio/minio pinned by digest, as vidra-core does):\n'
                         + '\n'.join(offenders))

    def test_the_pattern_distinguishes_quay_from_docker_hub(self):
        self.assertIsNone(DOCKER_HUB_MINIO.search('quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z'))
        self.assertIsNotNone(DOCKER_HUB_MINIO.search('docker run minio/minio:latest'))
        self.assertIsNotNone(DOCKER_HUB_MINIO.search('docker.io/minio/minio:latest'))
        self.assertIsNotNone(GCR_MIRROR_MINIO.search('mirror.gcr.io/minio/mc'))


if __name__ == '__main__':
    unittest.main()
