#!/usr/bin/env python3
"""Hosted-runner REC03 for one recorded release pair; exports no raw log/fact or credential."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace
import urllib.request

import rec03_pair
import rec03_split_proof
import sealed_recovery_support

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('release_pair', ROOT / 'scripts/ci/release-pair.py')
release_pair = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_pair)
# The first pending migration is read at the newer record's core commit: a commit
# hash names its bytes, and the running image's revision label is held to the same one.
CORE_SOURCE = 'https://raw.githubusercontent.com/yegamble/vidra-core'
MIGRATION_LIMIT = 1048576
PHASES = 'install data fp backup inject upgrade-fail recover backup2 rollback restore-refuse repin restore-ok split report'.split()
PROBE = 'instance=200 healthz=200 site=200 watch=200'
IMAGE_PHASES = {'install', 'upgrade-fail', 'recover', 'rollback', 'repin', 'restore-ok', 'split'}
OLD_IMAGE_PHASES = {'install', 'upgrade-fail', 'rollback'}
SERVICES = {'api', 'frontend', 'search', 'postgres', 'redis', 'worker', 'caddy', 'clamav',
            'migrate', 'search-migrate', 'prep-volumes'}
STEPS = {'install.sh': 'installer', 'setup': 'setup', 'setup --check': 'setup_check',
         'provision': 'provision', 'deploy.sh': 'deploy'}
PROBES = ('instance', 'healthz', 'site', 'watch')


class Failure(AssertionError):
    pass


def require(ok, reason):
    if not ok:
        raise Failure(reason)  # Reasons are constants, never raw command output.


def fingerprint(value):
    for key in ('orig', 'master', 'segsha'):
        require(re.search(rf'(?:^| ){key}=(?!e3b0c44298fc1c14)[a-f0-9]{{16}}(?: |$)', value), 'invalid media fingerprint')
    require('state=published' in value and re.search(r'renditions=\d', value), 'unpublished media')
    return hashlib.sha256(value.encode()).hexdigest()


def drill(old, new, sql):
    """One pair and what its facts are held against; refuses a pair with nothing to inject."""
    injection = rec03_pair.injection(sql)
    return SimpleNamespace(old=old, new=new, injection=injection, conflict=rec03_pair.conflict(injection))


def injected_migration_conflict(log, conflict):
    """Decode the published migrator's JSON event without exporting its error.

    slog JSON-escapes SQL's quoted identifiers. Searching the raw log misses
    the real conflict; searching arbitrary decoded fields could accept an
    unrelated event. Require this migrator failure and the injected object.
    """
    for line in log.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (isinstance(event, dict) and event.get('level') == 'ERROR'
                and event.get('msg') == 'migrate failed'
                and isinstance(event.get('error'), str)
                and event['error'].startswith('dbmigrate: apply migrations: ')
                and conflict.search(event['error'])):
            return True
    return False


def verify_running_images(phase, pair, inspect):
    """Check loaded bytes, not just the mutable tag printed by docker ps.

    Inspect data stays in memory: container Config.Env contains private keys.
    A tag pull may retain either the multiarch index or the platform RepoDigest.
    Both are recorded; also require the actual AMD64 image's source revision and
    config ID to match the running container, including the split worker.
    """
    if phase not in IMAGE_PHASES:
        return {}
    record = pair.old if phase in OLD_IMAGE_PHASES else pair.new
    services = {'api': 'core', 'frontend': 'user', 'search': 'search'}
    if phase == 'split':
        services['worker'] = 'core'
    containers = inspect(['bash', 'deploy/compose.sh', 'ps', '-q', *services]).split()
    require(len(containers) == len(services) and len(set(containers)) == len(services), 'missing running image services')
    rows = json.loads(inspect(['docker', 'inspect', *containers]))
    require(len(rows) == len(services), 'missing running image inspections')
    seen = {}
    for container in rows:
        service = container['Config']['Labels']['com.docker.compose.service']
        require(service in services and service not in seen and container['State']['Running'] is True, 'unexpected running image service')
        seen[service] = container
        component = record['components'][services[service]]
        image = component['image']
        info, = json.loads(inspect(['docker', 'image', 'inspect', container['Image']]))
        references = {image['repository'] + '@' + digest
                      for digest in (image['index_digest'], image['platforms']['linux/amd64'])}
        require(bool(references.intersection(info.get('RepoDigests', []))), 'running image digest differs')
        require(info['Os'] == 'linux' and info['Architecture'] == 'amd64', 'running image platform differs')
        require((info['Config'].get('Labels') or {}).get('org.opencontainers.image.revision') == component['commit'], 'running image revision differs')
        require(container['Image'] == info['Id'] and container['Config']['Image'] == image['repository'] + ':' + component['tag'], 'running image identity differs')
    return seen


def verify(phase, facts, previous, log, pair):
    """Driver records failures without exiting; its facts must decide the gate."""
    expected = {'install': ('install_exit', 0), 'backup': ('backup_exit', 0),
                'upgrade-fail': ('deploy_exit', 1), 'recover': ('deploy_exit', 0),
                'backup2': ('backup_exit', 0), 'rollback': ('rollback_exit', 0),
                'restore-refuse': ('restore_exit', 1), 'repin': ('deploy_exit', 0),
                'restore-ok': ('restore_exit', 0), 'split': ('deploy_exit', 0)}
    if phase in expected:
        field, nonzero = expected[phase]
        require(bool(re.fullmatch(r'\d+', facts.get(field, ''))), 'missing exit fact')
        require((int(facts[field]) != 0) == bool(nonzero), 'unexpected command exit')
    if phase not in ('backup', 'inject', 'backup2', 'report'):
        require('probe' in facts, 'missing HTTP probes')
        require(facts['probe'] == PROBE, 'HTTP probes failed')
    old, new = pair.old, pair.new
    ledger = rec03_pair.ledger(old, new, phase)
    if phase not in ('backup', 'backup2', 'split', 'report'):
        require(facts.get('ledger') == ledger, 'unexpected migration ledger')
    if phase in ('data', 'split'):
        require(facts.get('state' if phase == 'data' else 'video2_state') == 'published', 'upload did not publish')
    if phase in ('data', 'fp', 'upgrade-fail', 'recover', 'rollback', 'restore-ok'):
        require('fp' in facts, 'missing media fingerprint')
        digest = fingerprint(facts['fp'])
        if phase != 'data':
            require(digest == fingerprint(previous['data']['fp']), 'media changed across upgrade or restore')
    if phase == 'upgrade-fail':
        require(facts.get('pin_exit') == '0', 'bundle unpack failed')
        require(injected_migration_conflict(log, pair.conflict), 'migration conflict not observed')
    if phase == 'backup':
        require(facts.get('pre_core_version') == str(old['core_schema_version'])
                and facts.get('pre_search_version') == str(old['search_schema_version']), 'wrong backup ledger')
    if phase in ('backup', 'backup2'):
        dump = Path(facts.get('dump_pre' if phase == 'backup' else 'dump_post', ''))
        require(dump.is_file() and dump.stat().st_size > 0, 'backup dump missing')
    if phase == 'recover':
        require(facts.get('force_target') == str(old['core_schema_version'])
                and facts.get('post_core_version') == str(new['core_schema_version']), 'wrong recovery force target')
    if phase == 'backup2':
        require(facts.get('marker_http') == '200', 'marker write failed')
        require(facts.get('counts') != previous['data']['counts'], 'marker was not recorded')
    if phase == 'restore-refuse':
        require(facts.get('counts_before') == facts.get('counts_after'), 'refused restore changed data')
        require(all(pattern.search(log) for pattern in rec03_pair.refusal(old, new)), 'schema refusal not observed')
    if phase == 'restore-ok':
        require(facts.get('counts') == previous['data']['counts'], 'forward restore did not remove marker')
    if phase == 'split':
        require(facts.get('video2_packaging') == 'cmaf', 'split CMAF media missing')
        require('video2_fp' in facts, 'split media fingerprint missing')
        fingerprint(facts['video2_fp'])
    if phase in IMAGE_PHASES:
        require('images' in facts, 'missing running images')
        for image in rec03_pair.images(old if phase in OLD_IMAGE_PHASES else new):
            require(image in facts['images'], 'wrong running image tag')
    return {'status': 'PASS', 'media_fingerprint_verified': 'fp' in facts,
            **({'ledger': ledger} if 'ledger' in facts else {})}


def verify_phase(phase, facts, previous, log, pair, inspect):
    verdict = verify(phase, facts, previous, log, pair)
    containers = verify_running_images(phase, pair, inspect)
    if phase == 'split':
        try:
            rec03_split_proof.verify(facts, containers, pair.new['components']['core'],
                lambda sql: inspect(['bash', 'deploy/compose.sh', 'exec', '-T', 'postgres',
                    'psql', '-X', '-U', 'vidra', '-d', 'vidra', '-At', '-v', 'ON_ERROR_STOP=1', '-c', sql]))
        except rec03_split_proof.Invalid:
            require(False, 'split worker not proven')
    return verdict  # No phase PASS until both the facts and running bytes pass.


def diagnostics(private, facts):
    """Construct finite public facts; never copy log lines or Docker metadata."""
    result, steps = {}, {}
    try:
        with (private / 'install.private.log').open(errors='replace') as log:
            for line in log:
                match = re.fullmatch(r'\[rec03 install [0-9]{2}:[0-9]{2}:[0-9]{2}\] '
                                     r'(install\.sh|setup|setup --check|provision|deploy\.sh) exit=([0-9]{1,3})\n?', line)
                if match and int(match[2]) <= 255:
                    steps[STEPS[match[1]]] = int(match[2])
    except OSError:
        pass
    if steps:
        result['install_steps'] = steps
    try:
        labels = subprocess.check_output(['docker', 'ps', '--filter', 'label=com.docker.compose.service',
            '--format', '{{.Label "com.docker.compose.service"}}'], stderr=subprocess.DEVNULL, text=True, timeout=10)
        result['running_services'] = sorted(set(labels.splitlines()) & SERVICES)
    except (OSError, subprocess.SubprocessError):
        pass
    probe = facts.get('probe', '') if type(facts) is dict else ''
    if type(probe) is str and re.fullmatch(' '.join(name + r'=[0-9]{3}' for name in PROBES), probe):
        statuses = {name: int(code) for name, code in (item.split('=') for item in probe.split())
                    if int(code) == 0 or 100 <= int(code) <= 599}
        if statuses:
            result['probe_statuses'] = statuses
    return result


def require_small_resource_host():
    require((os.cpu_count() or 0) >= 4, 'small resource profile requires four CPUs')


def main(out):
    # Build output solely from booleans, validated SHAs and fixed labels. Never
    # serialize raw facts, errors, subprocess stdout, owner.json or backup paths.
    # `pair` stays empty until the records name one: a verdict never states a pair it did not resolve.
    result = {'status': 'FAIL', 'pair': [], 'phases': {}}
    phase, facts, created_private = 'preflight', {}, False
    try:
        ref, installer = os.environ.get('REC03_RECORD_REF', ''), os.environ.get('REC03_INSTALLER_REF', '')
        require(all(re.fullmatch('[a-f0-9]{40}', x) for x in (ref, installer)), 'immutable commits required')
        require(os.geteuid() == 0 and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'disposable hosted runner required')
        require_small_resource_host()
        root = Path(os.environ.get('REC03_RECORD_ROOT', ''))
        require(root.is_absolute() and sealed_recovery_support.head(root) == ref, 'record checkout differs')
        found = release_pair.resolve(root, os.environ.get('REC03_RELEASE', ''), os.environ.get('REC03_PREVIOUS', ''))
        old, new = found['old'], found['new']
        result['pair'] = [old['release'], new['release']]
        _, migration = rec03_pair.first_pending(old, new)
        with urllib.request.urlopen(f"{CORE_SOURCE}/{new['components']['core']['commit']}/migrations/{migration}", timeout=30) as response:
            sql = response.read(MIGRATION_LIMIT + 1)
        require(len(sql) <= MIGRATION_LIMIT, 'first pending migration too large')
        pair = drill(old, new, sql.decode())
        require(not Path('/opt/vidra').exists(), 'existing deployment refused')
        private = Path('/root/rec03')
        private.mkdir(mode=0o700)
        created_private = True
        os.umask(0o077)
        result.update(record_commit=ref, installer_commit=installer)
        env = {**os.environ, **rec03_pair.env(old, new, pair.injection), 'REC03_ALLOW_DOCKER': '1',
               'REC03_RESOURCE_PROFILE': 'small', 'REC03_ROOT': str(private), 'REC03_INSTALL': 'bundle'}
        with (private / 'preflight.log').open('w') as log:
            for data in (old, new):
                # The driver pins each release from this cache, so it reads the bytes resolved above.
                record = private / 'state/records' / f"{data['release']}.json"
                record.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(root / 'releases' / record.name, record)
                for component in data['components'].values():
                    image = component['image']
                    inspected = subprocess.check_output(['docker', 'buildx', 'imagetools', 'inspect', f"{image['repository']}:{component['tag']}", '--format', '{{json .Manifest}}'], stderr=log)
                    require(json.loads(inspected)['digest'] == image['index_digest'], 'published image digest drift')
        shutil.copy(ROOT / 'tests/rec03-envfix.py', '/root/rec03-envfix.py')
        shutil.copy(ROOT / 'deploy/release-mapping.py', '/root/release-mapping.py')
        previous = {}
        for phase in PHASES:
            facts = {}
            print(f'REC03: {phase}', flush=True)
            with (private / f'{phase}.private.log').open('w') as log:
                done = subprocess.run(['bash', str(ROOT / 'tests/rec03-upgrade-rollback.sh'), phase, 'baseline'], env=env, stdout=log, stderr=log, timeout=1800)
                require(done.returncode == 0, 'driver phase failed')
                facts = json.loads((private / 'facts' / f'{phase}.json').read_text()) if phase != 'report' else {}
                log.flush()
                verdict = verify_phase(phase, facts, previous, (private / f'{phase}.private.log').read_text(),
                    pair, lambda command: subprocess.check_output(
                        command, cwd='/opt/vidra', env=env, stderr=log, text=True, timeout=60))
            result['phases'][phase] = verdict
            previous[phase] = facts
        result['status'] = 'PASS'
    except Exception as error:
        result['failed_phase'] = phase
        fixed = isinstance(error, (Failure, release_pair.Refused, rec03_pair.Refused))
        result['failure'] = str(error) if fixed else type(error).__name__
        result['diagnostics'] = diagnostics(private, facts) if created_private else {}
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o755)  # Only this constructed public verdict is readable by the artifact action.
    summary = out / 'summary.json'
    summary.write_text(json.dumps(result, indent=2) + '\n')
    summary.chmod(0o644)
    print(f"REC03: {result['status']} (sanitized verdict only)")
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    raise SystemExit(main(parser.parse_args().out))
