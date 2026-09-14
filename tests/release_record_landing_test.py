"""How deploy/release.sh LANDS releases/<tag>.json after a full publish.

main is branch-protected (ci-required + enforce_admins), so a fresh record commit
pushed straight to main is REJECTED — and a release would again depend on someone
landing the record by hand, the exact out-of-band step finding #189 removes. The
record must instead land as a short-lived branch + an auto-opened PR, the way
every record to date did.

This exercises write_release_record itself: the function block is extracted from
deploy/release.sh between its markers and sourced into a harness with stub
git/gh/docker, so the command sequence is asserted without a real GitHub. Two
runs: the branch+PR path is taken (and a direct push to main is NOT), and a failed
`gh pr create` reports the branch + a by-hand PR recipe rather than "commit by
hand".
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SH = ROOT / 'deploy/release.sh'
SEAM = ROOT / 'deploy/release-record.py'
BEGIN = '# >>> release-record functions >>>'
END = '# <<< release-record functions <<<'

INDEX_DIGEST = 'sha256:' + 'a' * 64
PLATFORM_DIGEST = 'sha256:' + 'b' * 64
MANIFEST = json.dumps({
    'mediaType': 'application/vnd.oci.image.index.v1+json',
    'digest': INDEX_DIGEST,
    'manifests': [{'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                   'digest': PLATFORM_DIGEST, 'platform': {'os': 'linux', 'architecture': 'amd64'}}],
})

GIT_STUB = r'''#!/bin/sh
printf 'git %s\n' "$*" >> "$STUB_LOG"
case "$*" in
  *"rev-parse"*"^{commit}"*) echo "cccccccccccccccccccccccccccccccccccccccc" ;;
esac
exit 0
'''

GH_STUB = r'''#!/bin/sh
printf 'gh %s\n' "$*" >> "$STUB_LOG"
case "$*" in
  *"api"*"/commits/"*) echo "dddddddddddddddddddddddddddddddddddddddd" ;;
  *"api"*"contents/migrations"*) printf '0146_a.up.sql\n0100_b.up.sql\n' ;;
  *"pr create"*)
    if [ -n "${FAIL_PR:-}" ]; then echo "pull request create failed: protected" >&2; exit 1; fi
    echo "https://github.com/yegamble/vidra/pull/999" ;;
esac
exit 0
'''

DOCKER_STUB = ("#!/bin/sh\n"
               "printf 'docker %s\\n' \"$*\" >> \"$STUB_LOG\"\n"
               "case \"$*\" in\n"
               "  *\"imagetools inspect\"*) printf '%s\\n' '" + MANIFEST + "' ;;\n"
               "esac\n"
               "exit 0\n")

HARNESS = '''#!/usr/bin/env bash
set -euo pipefail
log()  { printf 'LOG %s\\n' "$*"; }
step() { printf 'STEP %s\\n' "$*"; }
OWNER=yegamble
META_REPO=vidra
TAG=v0.9.9
REPO_ROOT="@@ROOT@@"
RECORD_REL="releases/${TAG}.json"
RECORD_PATH="${REPO_ROOT}/${RECORD_REL}"
RECORD_HELPER="@@SEAM@@"
source "@@BLOCK@@"
write_release_record
'''


def extract_block():
    text = RELEASE_SH.read_text()
    begin, end = text.index(BEGIN), text.index(END)
    assert begin != -1 and end > begin, 'release.sh lost its release-record markers'
    return text[begin + len(BEGIN):end]


class LandingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        (self.repo / 'releases').mkdir(parents=True)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        for name, body in (('git', GIT_STUB), ('gh', GH_STUB), ('docker', DOCKER_STUB)):
            path = self.bin / name
            path.write_text(body)
            path.chmod(0o755)
        self.log = self.base / 'stub.log'
        block = self.base / 'block.sh'
        block.write_text(extract_block())
        harness = self.base / 'harness.sh'
        harness.write_text(HARNESS.replace('@@ROOT@@', str(self.repo))
                           .replace('@@SEAM@@', str(SEAM)).replace('@@BLOCK@@', str(block)))
        self.harness = harness

    def run_harness(self, fail_pr=False):
        env = {'PATH': f'{self.bin}:{os.environ["PATH"]}', 'STUB_LOG': str(self.log)}
        if fail_pr:
            env['FAIL_PR'] = '1'
        result = subprocess.run(['bash', str(self.harness)], capture_output=True, text=True, env=env)
        calls = self.log.read_text() if self.log.exists() else ''
        return result, calls

    def test_record_lands_via_a_branch_and_a_pr_not_a_direct_push_to_main(self):
        result, calls = self.run_harness()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # the branch is created and pushed
        self.assertIn('checkout -b releases/record-v0.9.9', calls)
        self.assertIn('push -u origin releases/record-v0.9.9', calls)
        # a PR is opened against main from that branch
        self.assertRegex(calls, r'gh pr create .*--base main .*--head releases/record-v0\.9\.9')
        self.assertIn('https://github.com/yegamble/vidra/pull/999', result.stdout + result.stderr)
        # and NOT a direct push to the protected branch
        self.assertNotIn('HEAD:main', calls)
        self.assertNotIn('push origin main', calls)

    def test_the_record_it_writes_is_a_completed_record_not_a_skeleton(self):
        result, _ = self.run_harness()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads((self.repo / 'releases/v0.9.9.json').read_text())
        self.assertEqual(record['schema_version'], 1)
        for name in ('core', 'user', 'search'):
            image = record['components'][name]['image']
            self.assertEqual(image['index_digest'], INDEX_DIGEST)
            self.assertEqual(image['platforms'], {'linux/amd64': PLATFORM_DIGEST})

    def test_a_failed_pr_create_reports_the_branch_and_a_by_hand_pr_recipe(self):
        result, calls = self.run_harness(fail_pr=True)
        self.assertNotEqual(result.returncode, 0)
        out = result.stdout + result.stderr
        # the branch is already pushed; the operator is pointed at opening the PR,
        # never at committing the record by hand.
        self.assertIn('push -u origin releases/record-v0.9.9', calls)
        self.assertIn('releases/record-v0.9.9', out)
        self.assertIn('gh pr create', out)
        self.assertNotIn('HEAD:main', calls)


if __name__ == '__main__':
    unittest.main()
