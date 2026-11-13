#!/usr/bin/env python3
"""Validate sanitized verdicts against the release records and write a neutral Check Runs payload; no network."""
import argparse
import ast
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


release_pair = module('release_pair', 'scripts/ci/release-pair.py')
LIMIT = 32768
PHASES = 'install data fp backup inject upgrade-fail recover backup2 rollback restore-refuse repin restore-ok split report'.split()
MEDIA = {'data', 'fp', 'upgrade-fail', 'recover', 'rollback', 'restore-ok'}
LEDGER = set(PHASES) - {'backup', 'backup2', 'split', 'report'}
BEFORE_UPGRADE = {'install', 'data', 'fp', 'inject'}
SCOPE = 'published-image synthetic cross-VM sealed-secret subset'
RESULTS = {'success', 'failure', 'cancelled', 'skipped'}
COMMON = {'status', 'scope', 'synthetic_only', 'phase', 'external_delivery_blocked',
          'release', 'record_commit', 'tool_commit', 'core_schema', 'search_schema'}
RESTORE = {'different_runner_boot', 'empty_destination', 'backup_hash_match', 'schema_and_catalogue_match',
           'wrong_key_refused', 'mfa_wrong_code_refused', 'mfa_correct_code_accepted', 'oidc_disabled',
           'mail_secret_status', 'oidc_secret_status'}
SERVICES = set('api frontend search postgres redis worker caddy clamav migrate search-migrate prep-volumes'.split())
SEALED_PHASES = {
    'source': set('preconditions published-assets fixture migrations start-services ready owner-claim api-fixture snapshot backup complete'.split()),
    'replacement': set(('preconditions published-assets restore-infrastructure restore-relay restore restore-ready restore-snapshot restore-verify '
                        'wrong-key-start wrong-key-ready wrong-key-verify original-key-start original-key-ready '
                        'original-key-verify complete').split())}


class Invalid(ValueError):
    pass


def require(ok):
    if not ok:
        raise Invalid()


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Invalid()  # argparse normally echoes attacker-controlled values.


def keys(value, allowed, required=()):
    require(type(value) is dict and set(value) <= allowed and set(required) <= set(value))


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def identities(value, expected):
    for field, wanted in expected.items():
        if field in value:
            require(type(value[field]) is type(wanted) and value[field] == wanted)


def failure_reasons():
    tree = ast.parse((ROOT / 'tests/rec03-runner.py').read_text())
    reasons = {n.args[1].value for n in ast.walk(tree) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name) and n.func.id == 'require' and len(n.args) > 1
               and isinstance(n.args[1], ast.Constant) and type(n.args[1].value) is str}
    # The runner's preflight refusals: the pair the records do not name, and the pair it cannot drill.
    reasons |= set(release_pair.REASONS) | set(module('rec03_pair', 'tests/rec03_pair.py').REASONS)
    return reasons | {name for name in dir(builtins) if isinstance(getattr(builtins, name), type)
                      and issubclass(getattr(builtins, name), Exception)} | {
                          'HTTPError', 'URLError', 'TimeoutExpired', 'CalledProcessError'}


def diagnostics(value):
    keys(value, {'install_steps', 'running_services', 'probe_statuses'})
    for field, names, low, high in (
            ('install_steps', {'installer', 'setup', 'setup_check', 'provision', 'deploy'}, 0, 255),
            ('probe_statuses', {'instance', 'healthz', 'site', 'watch'}, 100, 599)):
        if field in value:
            keys(value[field], names)
            require(all(type(code) is int and (low <= code <= high or field == 'probe_statuses' and code == 0)
                        for code in value[field].values()))
    if 'running_services' in value:
        services = value['running_services']
        require(type(services) is list and len(services) <= len(SERVICES)
                and all(type(service) is str and service in SERVICES for service in services)
                and len(set(services)) == len(services))


def recorded(args):
    """What the records at the record commit say: (old, new) for rec03, one record for sealed,
    None where they name nothing. Read here, never taken from the verdict being checked."""
    try:
        if args.kind == 'rec03':
            found = release_pair.resolve(args.record_root, args.release, args.previous)
            return found['old'], found['new']
        return release_pair.records(args.record_root).get(args.release)
    except release_pair.Refused:
        return None


def ledger(pair, phase):
    old, new = pair
    if phase in BEFORE_UPGRADE:
        return f"core={old['core_schema_version']}:false search={old['search_schema_version']}:false"
    if phase == 'upgrade-fail':
        # The first pending migration, dirty; the search migrator never ran.
        return f"core={old['core_schema_version'] + 1}:true search={old['search_schema_version']}:false"
    return f"core={new['core_schema_version']}:false search={new['search_schema_version']}:false"


def rec03(value, args, pair):
    allowed = {'status', 'pair', 'phases', 'record_commit', 'installer_commit', 'failed_phase', 'failure', 'diagnostics'}
    keys(value, allowed, {'status', 'pair', 'phases'})
    require(value['status'] in ('PASS', 'FAIL'))
    identities(value, {'record_commit': args.record_commit, 'installer_commit': args.tool_commit})
    keys(value['phases'], set(PHASES))
    # An empty pair is the runner saying the records named none: only a preflight failure can say it.
    unnamed = (value['pair'] == [] and value['status'] == 'FAIL' and value.get('failed_phase') == 'preflight'
               and not value['phases'])
    require(unnamed or pair is not None and value['pair'] == [pair[0]['release'], pair[1]['release']])
    # A phase only runs for a pair with a core migration to fail.
    require(not value['phases'] or pair[1]['core_schema_version'] > pair[0]['core_schema_version'])
    complete = {'record_commit', 'installer_commit'} <= set(value) and set(value['phases']) == set(PHASES)
    for phase, facts in value['phases'].items():
        required = {'status', 'media_fingerprint_verified'} | ({'ledger'} if phase in LEDGER else set())
        keys(facts, required)
        identities(facts, {'status': 'PASS', 'media_fingerprint_verified': phase in MEDIA, 'ledger': ledger(pair, phase)})
        complete = complete and required <= set(facts)
    if 'failed_phase' in value:
        require(value['failed_phase'] in ['preflight', *PHASES])
    if 'failure' in value:
        require(type(value['failure']) is str and value['failure'] in failure_reasons())
    if 'diagnostics' in value:
        require(value['status'] == 'FAIL')
        diagnostics(value['diagnostics'])
    if value['status'] == 'PASS':
        require(not {'failure', 'failed_phase'} & set(value))
    return complete


def sealed(value, args, role, record):
    fields = COMMON | (RESTORE if role == 'replacement' else set())
    keys(value, fields | {'diagnostics'}, {'status', 'scope', 'synthetic_only', 'phase'})
    require(value['status'] in ('PASS', 'FAIL'))
    require(value['phase'] in SEALED_PHASES[role])
    if 'diagnostics' in value:
        require(value['status'] == 'FAIL')
        facts = value['diagnostics']
        keys(facts, {'readyz_status', 'services'})
        require(bool(facts))
        if 'readyz_status' in facts:
            code = facts['readyz_status']
            require(type(code) is int and (code == 0 or 100 <= code <= 599))
        if 'services' in facts:
            keys(facts['services'], {'api', 'search', 'frontend', 'postgres', 'redis'})
            require(bool(facts['services']) and all(type(state) is str and state in {
                'missing', 'stopped', 'restarting', 'starting', 'healthy', 'unhealthy', 'running'}
                for state in facts['services'].values()))
    expected = {'scope': SCOPE, 'synthetic_only': True, 'record_commit': args.record_commit,
                'tool_commit': args.tool_commit, 'release': args.release, 'external_delivery_blocked': True}
    if record is None:
        # No usable record, so no schema to hold the verdict to: it may not state one.
        require(not {'core_schema', 'search_schema'} & set(value))
    else:
        expected.update(core_schema=record['core_schema_version'], search_schema=record['search_schema_version'])
    if role == 'replacement':
        expected.update({key: 'ok' if key.endswith('_secret_status') else True for key in RESTORE})
    identities(value, expected)
    return set(value) == fields and value['phase'] == 'complete'


def load(path, args, role, expected):
    if path is None or not path.exists():
        return None
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    require(len(data) <= LIMIT)
    value = json.loads(data, object_pairs_hook=unique)
    complete = rec03(value, args, expected) if args.kind == 'rec03' else sealed(value, args, role, expected)
    # Never publish a partial input's PASS label, even as a nested verdict.
    if value['status'] == 'PASS' and not complete:
        value['status'] = 'INCOMPLETE'
    return {'sha256': hashlib.sha256(data).hexdigest(), 'verdict': value}


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--kind', choices=('rec03', 'sealed'), required=True)
    for field in ('source', 'replacement', 'out'):
        parser.add_argument('--' + field, type=Path, required=field == 'out')
    for field in ('source-result', 'replacement-result'):
        parser.add_argument('--' + field, choices=sorted(RESULTS), required=field == 'source-result')
    for field in ('record-commit', 'tool-commit', 'run-id', 'run-attempt', 'repository'):
        parser.add_argument('--' + field, required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--previous', default='')
    parser.add_argument('--record-root', type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        require(all(re.fullmatch('[a-f0-9]{40}', x) for x in (args.record_commit, args.tool_commit)))
        require(all(re.fullmatch('[1-9][0-9]{0,19}', x) for x in (args.run_id, args.run_attempt)))
        require(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}', args.repository)
                and args.repository.split('/')[1] not in ('.', '..'))
        require(release_pair.tag(args.release) and (not args.previous or release_pair.tag(args.previous)))
        require(args.replacement_result in RESULTS and not args.previous if args.kind == 'sealed'
                else args.replacement is None and args.replacement_result is None)
        # The expectations below are read from this checkout, so it has to be the commit the payload names.
        require(args.record_root.is_absolute() and subprocess.check_output(
            ['git', '-c', 'safe.directory=' + str(args.record_root.resolve()), '-C', str(args.record_root),
             'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip() == args.record_commit)
        expected = recorded(args)
        context = {field: getattr(args, field) for field in ('repository', 'record_commit', 'tool_commit', 'release')}
        context.update(run_id=int(args.run_id), run_attempt=int(args.run_attempt))
        if args.previous:
            context['previous'] = args.previous
        roles, missing = {}, []
        for role in (('source',) if args.kind == 'rec03' else ('source', 'replacement')):
            item = load(getattr(args, role), args, role, expected)
            roles[role] = {'job_result': getattr(args, role + '_result'), **(item or {})}
            if item is None:
                missing.append(role)
            elif item['verdict']['status'] == 'INCOMPLETE':
                missing.append(role + '.required_fields')
        status = 'INCOMPLETE' if missing else 'PASS' if all(
            item['job_result'] == 'success' and item['verdict']['status'] == 'PASS' for item in roles.values()) else 'FAIL'
        summary = json.dumps({'kind': args.kind, 'status': status, 'informational_only': True,
                              'context': context, 'roles': roles, 'missing': missing}, sort_keys=True, indent=2)
        require(len(summary.encode()) <= LIMIT - 12)
        url = f'https://github.com/{args.repository}/actions/runs/{args.run_id}/attempts/{args.run_attempt}'
        payload = {'name': f'runtime-verdict/{args.kind}/{args.run_id}/{args.run_attempt}', 'head_sha': args.tool_commit,
                   'status': 'completed', 'conclusion': 'neutral', 'details_url': url,
                   'external_id': f'{args.kind}:{args.run_id}:{args.run_attempt}:{args.record_commit}',
                   'output': {'title': f'Runtime verdict: {status} (informational)', 'summary': '```json\n' + summary + '\n```'}}
        with args.out.open('x') as output:
            json.dump(payload, output)
        return 0
    except Exception:
        print('runtime verdict rejected', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
