"""Read-only evidence completion for the recorded B2 checksum-field failure.

Preserves the original FAIL. Never resumes application mutations or labels a
failed browser/install sequence successful; only completes provider readback
and the post-browser image/ledger snapshot that the old assertion prevented.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

from blank_server_smoke import require, sha
from release_acceptance import Recorder, runtime_snapshot, save
from release_acceptance_b2 import TestBucket
from runtime_smoke import check_ledger


def complete(stage, out, credentials):
    raw = json.loads((stage / 'result.json').read_text())
    browser = json.loads((stage / 'browser-result.json').read_text())
    require(raw['status'] == 'FAIL' and raw['error'] == 'B2 does not attest the uploaded original bytes',
            'only the known provider-metadata assertion can be completed here')
    require(browser == raw['browser'] and browser['status'] == 'PASS', 'browser sequence did not pass')
    require(raw['checks']['blank_native_host'] == raw['checks']['installed_migrated_serving'] == 'PASS',
            'fresh install and deployed candidate were not established')
    require(sha(stage / 'fixture.mp4') == browser['original']['sha256'], 'fixture/browser download mismatch')
    for name, expected in json.loads((stage / 'handoff.json').read_text())['files'].items():
        require(sha(stage / name) == expected, 'original handoff changed: ' + name)
    out.mkdir(mode=0o700)
    run = Recorder(out)
    result = {'status': 'UNVERIFIED', 'started_at': time.time(),
              'original_result_sha256': sha(stage / 'result.json'),
              'original_browser_sha256': sha(stage / 'browser-result.json'),
              'original_run_status': raw['status'], 'original_error': raw['error'],
              'scope': 'Only provider GET/list/auth and read-only container/ledger observations; no application mutation or rebuild.'}
    try:
        spec = json.loads((stage / 'storage.json').read_text())['spec']
        bucket = TestBucket(spec, json.loads(credentials.read_text()))
        require(raw['storage']['before'] == [] and raw['storage']['bucket_id'] == spec['bucket_id'],
                'initial empty dedicated bucket not established')
        shutil.copyfile(stage / 'fixture.mp4', out / 'fixture.mp4')
        result['storage'] = bucket.verify_media(browser['video_id'], out / 'fixture.mp4')
        result['storage']['before'] = raw['storage']['before']
        candidate = json.loads((stage / 'candidate.json').read_text())
        result['runtime_after_browser'] = runtime_snapshot(run, candidate)
        result['ledgers'] = {}
        for table, expected in json.loads((stage / 'expected-ledgers.json').read_text()).items():
            actual = run.sql(f'SELECT version, dirty FROM {table}')
            check_ledger(actual, expected['version'])
            result['ledgers'][table] = actual
        result['status'] = 'PASS'
    except Exception as error:
        result.update(status='FAIL', error=str(error))
    finally:
        result['finished_at'] = time.time()
        result['helper_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        save(out / 'completion.json', result)
    print(json.dumps({'status': result['status'], 'error': result.get('error'), 'completion_sha256': sha(out / 'completion.json')}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--b2-credentials', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(complete(args.stage, args.out, args.b2_credentials))
