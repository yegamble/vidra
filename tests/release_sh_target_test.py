"""deploy/release.sh pins the cut set: every release is created AT the commit
that was confirmed (council ruling v0.7.6, D9).

`gh release create` without --target tags the repo's default branch as of THAT
call, and release.sh makes one call per repo with an image build in between, so
a PR merged mid-run shipped in the release without anyone choosing it. Now the
pre-flight resolves each target repo's default-branch HEAD, the confirmation
shows them, and each create passes `--target <that sha>`.

The whole script runs against a throwaway meta checkout (a real git repo with a
local bare `origin` named .../yegamble/vidra.git) and a fake `gh` on PATH that
records its argv as JSON lines, so the assertions are about what release.sh
actually asked GitHub to do. A subset release (the v0.7.6 shape: core + user,
search held back) keeps the run free of the record-writing tail; one full run
checks the record PR's body says what that PR really needs.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TAG = 'v0.9.9'
SHAS = {'vidra-core': 'c' * 40, 'vidra-user': 'a' * 40, 'vidra-search': 'e' * 40}

GH_STUB = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.environ['GH_LOG'], 'a') as log:
    log.write(json.dumps(argv) + '\n')
joined = ' '.join(argv)
shas = json.loads(os.environ['GH_SHAS'])
broken = os.environ.get('GH_BROKEN_REPO', '')
if argv[:2] == ['auth', 'status']:
    sys.exit(0)
if argv[:1] == ['version']:
    print('gh version 2.99.0 (stub)'); sys.exit(0)
if argv[:2] == ['api', 'user']:
    print('tester'); sys.exit(0)
if argv[:1] == ['api']:
    path = argv[1]
    if '/git/ref/tags/' in path:
        sys.exit(1)                      # every tag is free
    parts = path.split('/')
    repo = parts[2] if len(parts) > 2 else ''
    if len(parts) == 3 and '.default_branch' in joined:
        print('main'); sys.exit(0)
    if '/git/ref/heads/' in path:
        if repo == broken:
            print('{"message":"Not Found"}', file=sys.stderr); sys.exit(1)
        print(shas[repo]); sys.exit(0)
    if '/commits/' in path:
        print(shas.get(repo, 'd' * 40)); sys.exit(0)
    if 'contents/migrations' in path:
        print('0151_a.up.sql\n0100_b.up.sql'); sys.exit(0)
    sys.exit(0)
if argv[:2] == ['release', 'create']:
    sys.exit(0)
if argv[:2] == ['run', 'list']:
    print('4242'); sys.exit(0)
if argv[:2] == ['run', 'view']:
    print('https://github.com/yegamble/x/actions/runs/4242'); sys.exit(0)
if argv[:2] == ['run', 'watch']:
    sys.exit(0)
if argv[:2] == ['pr', 'create']:
    print('https://github.com/yegamble/vidra/pull/999'); sys.exit(0)
sys.exit(0)
'''

INDEX = 'sha256:' + '1' * 64
PLATFORM = 'sha256:' + '2' * 64
DOCKER_STUB = ('#!/bin/sh\ncase "$*" in\n  *"imagetools inspect"*) printf \'%s\\n\' \''
               + json.dumps({'mediaType': 'application/vnd.oci.image.index.v1+json', 'digest': INDEX,
                             'manifests': [{'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                                            'digest': PLATFORM,
                                            'platform': {'os': 'linux', 'architecture': 'amd64'}}]})
               + "' ;;\nesac\nexit 0\n")


def git(cwd, *args):
    subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True)


class ReleaseTargetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.repo = base / 'meta'
        (self.repo / 'deploy').mkdir(parents=True)
        (self.repo / 'releases').mkdir()
        for name in ('release.sh', 'release-record.py', 'release-mapping.py'):
            shutil.copy2(ROOT / 'deploy' / name, self.repo / 'deploy' / name)
        (self.repo / 'releases/.keep').write_text('')
        remote = base / 'remote/yegamble/vidra.git'
        remote.parent.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(remote)], check=True)
        git(base, 'init', '-q', '-b', 'main', str(self.repo))
        for key, value in (('user.name', 't'), ('user.email', 't@example.invalid'), ('commit.gpgsign', 'false'),
                           ('tag.gpgsign', 'false')):
            git(self.repo, 'config', key, value)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'meta')
        git(self.repo, 'remote', 'add', 'origin', str(remote))
        git(self.repo, 'push', '-q', 'origin', 'main')
        git(self.repo, 'branch', '-q', '--set-upstream-to=origin/main')
        self.bin = base / 'bin'
        self.bin.mkdir()
        for name, body in (('gh', GH_STUB), ('docker', DOCKER_STUB)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.log = base / 'gh.log'

    def run_release(self, *repos, broken='', tty_answer=None):
        env = dict(os.environ, PATH=f'{self.bin}:{os.environ["PATH"]}', GH_LOG=str(self.log),
                   GH_SHAS=json.dumps(SHAS), GH_BROKEN_REPO=broken, RUN_APPEAR_TIMEOUT='5',
                   GITHUB_OWNER='yegamble')
        argv = ['bash', str(self.repo / 'deploy/release.sh'), '--yes', TAG, *repos]
        if tty_answer is None:
            result = subprocess.run(argv, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        else:
            # The interactive prompt, on a real pty (util-linux `script`).
            argv.remove('--yes')
            result = subprocess.run(['script', '-qec', ' '.join(argv), '/dev/null'], input=tty_answer + '\n',
                                    capture_output=True, text=True, env=env)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, calls

    @staticmethod
    def creates(calls):
        return [c for c in calls if c[:2] == ['release', 'create']]

    @staticmethod
    def repo_of(call):
        return call[call.index('-R') + 1].split('/')[1]

    @staticmethod
    def target_of(call):
        return call[call.index('--target') + 1] if '--target' in call else None

    def shown_cut_set(self, out):
        """{repo: sha} as the confirmation printed it: '  <repo> <branch> @ <sha>'."""
        shown = {}
        for line in out.splitlines():
            words = line.split()
            if len(words) == 4 and words[0] in SHAS and words[2] == '@':
                shown[words[0]] = words[3]
        return shown

    def test_every_create_targets_the_sha_the_confirmation_showed(self):
        result, calls = self.run_release('vidra-core', 'vidra-user')
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        creates = self.creates(calls)
        self.assertEqual([self.repo_of(c) for c in creates], ['vidra-core', 'vidra-user'])
        passed = {self.repo_of(c): self.target_of(c) for c in creates}
        self.assertEqual(passed, {'vidra-core': SHAS['vidra-core'], 'vidra-user': SHAS['vidra-user']})
        self.assertEqual(self.shown_cut_set(out), passed)
        # The cut set is shown BEFORE the first release is created.
        self.assertLess(out.index(SHAS['vidra-user']), out.index('publishing yegamble/vidra-core'))

    def test_the_interactive_prompt_shows_the_cut_set_it_then_targets(self):
        result, calls = self.run_release('vidra-core', 'vidra-user', tty_answer=TAG)
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        prompt = out[out.index('About to PUBLISH'):out.index('to confirm')]
        passed = {self.repo_of(c): self.target_of(c) for c in self.creates(calls)}
        self.assertEqual(self.shown_cut_set(prompt), passed)
        self.assertEqual(passed, {'vidra-core': SHAS['vidra-core'], 'vidra-user': SHAS['vidra-user']})

    def test_the_cut_set_is_resolved_before_any_create(self):
        _, calls = self.run_release('vidra-core', 'vidra-user')
        heads = [i for i, c in enumerate(calls) if c[:1] == ['api'] and '/git/ref/heads/' in c[1]]
        first_create = next(i for i, c in enumerate(calls) if c[:2] == ['release', 'create'])
        self.assertEqual(len(heads), 2)
        self.assertLess(max(heads), first_create)

    def test_an_unresolvable_head_refuses_before_any_create_or_meta_tag(self):
        result, calls = self.run_release('vidra-core', 'vidra-user', broken='vidra-user')
        out = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, out)
        self.assertIn('could not resolve yegamble/vidra-user main to a commit', out)
        self.assertEqual(self.creates(calls), [])
        tags = subprocess.run(['git', '-C', str(self.repo), 'ls-remote', '--tags', 'origin'],
                              capture_output=True, text=True, check=True).stdout
        self.assertEqual(tags.strip(), '', 'the meta tag was pushed before the refusal')

    def test_a_full_release_targets_all_three_and_the_record_pr_names_what_it_needs(self):
        result, calls = self.run_release()
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        passed = {self.repo_of(c): self.target_of(c) for c in self.creates(calls)}
        self.assertEqual(passed, SHAS)
        self.assertEqual(self.shown_cut_set(out), SHAS)
        pr = next(c for c in calls if c[:2] == ['pr', 'create'])
        body = pr[pr.index('--body') + 1]
        self.assertNotIn('trivially', body)
        for needed in ('release-preflight.py --tag v0.9.9', 'docs/evidence/release-v0.9.9-verification',
                       'RAW_PREFLIGHT_RELEASES', 'env/production.env.example', 'env/staging.env.example',
                       'tests/env_template_pins_test.py', 'RED'):
            self.assertIn(needed, body)


if __name__ == '__main__':
    unittest.main()
