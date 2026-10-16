"""T7/T9 evidence failures must fail the real spike script, without a live node."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / 'docs/evidence/ipfs-reference-pinning-spike-2026-09-20'

CURL_STUB = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith('http'))
if '/api/v0/add?' in url:
    print(json.dumps({'Hash': 'big' if 'chunker=' in url else 'default'}))
elif '/api/v0/filestore/ls?' in url:
    print('{"Size":1048576}')
else:
    output = pathlib.Path(args[args.index('-o') + 1])
    scenario = os.environ.get('SPIKE_SCENARIO', '')
    if '-r' in args:
        start = int(args[args.index('-r') + 1].split('-')[0])
        index = start // 8388608
        data = f'range-{index}\n'.encode()
        if scenario == 'range-mismatch' and index == 2:
            data = b'wrong range\n'
        output.write_bytes(data)
        print(f'range {index} http=206 size={len(data)}')
        # Keep matching bytes so this failure can only be caught via wait's status.
        if scenario == 'parallel-curl-failure' and index == 4:
            sys.exit(22)
    else:
        data = b'payload\n'
        if scenario == output.stem:
            data = b'wrong payload\n'
        output.write_bytes(data)
        if '-w' in args:
            print('0.010')
'''

SHASUM_STUB = r'''#!/usr/bin/env python3
import hashlib, pathlib, sys
name = sys.argv[3] if len(sys.argv) > 3 else None
data = pathlib.Path(name).read_bytes() if name else sys.stdin.buffer.read()
print(hashlib.sha256(data).hexdigest(), name or '-')
'''

DD_STUB = r'''#!/usr/bin/env python3
import sys
start = next(int(arg.split('=')[1]) for arg in sys.argv[1:] if arg.startswith('skip='))
sys.stdout.write(f'range-{start // 8388608}\n')
'''


class ReferencePinningSpikeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tree = Path(self.temp.name)
        for name in ('t789.sh', 'lib.sh'):
            shutil.copyfile(SPIKE / name, self.tree / name)
        data = self.tree / 'origin-root'
        data.mkdir()
        for name in ('payload1.bin', 'payload2.bin'):
            (data / name).write_bytes(b'payload\n')
        self.bin = self.tree / 'bin'
        self.bin.mkdir()
        for name, body in (('curl', CURL_STUB), ('shasum', SHASUM_STUB), ('dd', DD_STUB),
                           ('docker', '#!/bin/sh\necho "fixture daemon healthy"\n')):
            path = self.bin / name
            path.write_text(body)
            path.chmod(0o755)

    def run_spike(self, scenario=''):
        return subprocess.run(
            ['bash', str(self.tree / 't789.sh')], cwd=self.tree,
            env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
                 'SPIKE_SCENARIO': scenario}, capture_output=True, text=True, timeout=15,
        )

    def test_matching_full_and_range_reads_succeed(self):
        result = self.run_spike()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('t7-def bytes MATCH', result.stdout)
        self.assertIn('t7-big bytes MATCH', result.stdout)
        self.assertIn('all curls exited 0: yes', result.stdout)
        for index in range(8):
            self.assertIn(f'range {index}: MATCH', result.stdout)

    def test_either_full_read_mismatch_fails_even_when_later_ranges_match(self):
        for scenario in ('t7-def', 't7-big'):
            with self.subTest(scenario=scenario):
                result = self.run_spike(scenario)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(f'{scenario} MISMATCH', result.stdout)
                self.assertIn('range 7: MATCH', result.stdout)

    def test_any_range_mismatch_fails_after_collecting_the_remaining_evidence(self):
        result = self.run_spike('range-mismatch')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('range 2: MISMATCH', result.stdout)
        self.assertIn('range 7: MATCH', result.stdout)

    def test_parallel_curl_failure_fails_even_if_every_range_has_matching_bytes(self):
        result = self.run_spike('parallel-curl-failure')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('all curls exited 0: NO', result.stdout)
        self.assertNotIn('MISMATCH', result.stdout)
        for index in range(8):
            self.assertIn(f'range {index}: MATCH', result.stdout)


if __name__ == '__main__':
    unittest.main()
