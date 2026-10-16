#!/usr/bin/env python3
"""Hosted-runner REC03 v0.7.7 -> v0.7.8; exports no raw log/fact or credential."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
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


def injected_migration_conflict(log):
    """Decode the published migrator's JSON event without exporting its error.

    slog JSON-escapes SQL's quoted identifiers. Searching the raw log misses
    the real conflict; searching arbitrary decoded fields could accept an
    unrelated event. Require this migrator failure and the injected relation.
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
                and re.search(r'column "is_sensitive" of relation "remote_videos" already exists\b', event['error'])):
            return True
    return False


def verify_running_images(phase, records, inspect):
    """Check loaded bytes, not just the mutable tag printed by docker ps.

    Inspect data stays in memory: container Config.Env contains private keys.
    A tag pull may retain either the multiarch index or the platform RepoDigest.
    Both are recorded; also require the actual AMD64 image's source revision and
    config ID to match the running container, including the split worker.
    """
    if phase not in IMAGE_PHASES:
        return
    record = records['v0.7.7' if phase in OLD_IMAGE_PHASES else 'v0.7.8']
    services = {'api': 'core', 'frontend': 'user', 'search': 'search'}
    if phase == 'split':
        services['worker'] = 'core'
    containers = inspect(['bash', 'deploy/compose.sh', 'ps', '-q', *services]).split()
    require(len(containers) == len(services) and len(set(containers)) == len(services), 'missing running image services')
    rows = json.loads(inspect(['docker', 'inspect', *containers]))
    require(len(rows) == len(services), 'missing running image inspections')
    seen = set()
    for container in rows:
        service = container['Config']['Labels']['com.docker.compose.service']
        require(service in services and service not in seen and container['State']['Running'] is True, 'unexpected running image service')
        seen.add(service)
        component = record['components'][services[service]]
        image = component['image']
        info, = json.loads(inspect(['docker', 'image', 'inspect', container['Image']]))
        references = {image['repository'] + '@' + digest
                      for digest in (image['index_digest'], image['platforms']['linux/amd64'])}
        require(bool(references.intersection(info.get('RepoDigests', []))), 'running image digest differs')
        require(info['Os'] == 'linux' and info['Architecture'] == 'amd64', 'running image platform differs')
        require((info['Config'].get('Labels') or {}).get('org.opencontainers.image.revision') == component['commit'], 'running image revision differs')
        require(container['Image'] == info['Id'] and container['Config']['Image'] == image['repository'] + ':' + component['tag'], 'running image identity differs')


def verify(phase, facts, previous, log):
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
    if phase in ('install', 'data', 'fp', 'backup', 'inject'):
        ledger = 'core=151:false search=18:false'
    else:
        ledger = 'core=152:true search=18:false' if phase == 'upgrade-fail' else 'core=182:false search=18:false'
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
        require(injected_migration_conflict(log), 'migration conflict not observed')
    if phase == 'backup':
        require(facts.get('pre_core_version') == '151' and facts.get('pre_search_version') == '18', 'wrong backup ledger')
    if phase in ('backup', 'backup2'):
        dump = Path(facts.get('dump_pre' if phase == 'backup' else 'dump_post', ''))
        require(dump.is_file() and dump.stat().st_size > 0, 'backup dump missing')
    if phase == 'recover':
        require(facts.get('force_target') == '151' and facts.get('post_core_version') == '182', 'wrong recovery force target')
    if phase == 'backup2':
        require(facts.get('marker_http') == '200', 'marker write failed')
        require(facts.get('counts') != previous['data']['counts'], 'marker was not recorded')
    if phase == 'restore-refuse':
        require(facts.get('counts_before') == facts.get('counts_after'), 'refused restore changed data')
        require('dump is at 182' in log and 'carries up to 151' in log and 'Nothing was changed' in log, 'schema refusal not observed')
    if phase == 'restore-ok':
        require(facts.get('counts') == previous['data']['counts'], 'forward restore did not remove marker')
    if phase == 'split':
        require(int(facts.get('workers', '0')) >= 1 and facts.get('api_ffmpeg_mentions') == '0', 'split worker not proven')
    if phase in IMAGE_PHASES:
        require('images' in facts, 'missing running images')
        old = phase in OLD_IMAGE_PHASES
        for role in ('core', 'user', 'search'):
            tag = ('v0.7.3' if role == 'search' else 'v0.7.7') if old else 'v0.7.8'
            require(f'ghcr.io/yegamble/vidra-{role}:{tag};' in facts['images'], 'wrong running image tag')
    return {'status': 'PASS', 'media_fingerprint_verified': 'fp' in facts,
            **({'ledger': ledger} if 'ledger' in facts else {})}


def verify_phase(phase, facts, previous, log, records, inspect):
    verdict = verify(phase, facts, previous, log)
    verify_running_images(phase, records, inspect)
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
    result = {'status': 'FAIL', 'pair': ['v0.7.7', 'v0.7.8'], 'phases': {}}
    phase, facts, created_private = 'preflight', {}, False
    try:
        ref, installer = os.environ.get('REC03_RECORD_REF', ''), os.environ.get('REC03_INSTALLER_REF', '')
        require(all(re.fullmatch('[a-f0-9]{40}', x) for x in (ref, installer)), 'immutable commits required')
        require(os.geteuid() == 0 and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'disposable hosted runner required')
        require_small_resource_host()
        require(not Path('/opt/vidra').exists(), 'existing deployment refused')
        private = Path('/root/rec03')
        private.mkdir(mode=0o700)
        created_private = True
        os.umask(0o077)
        result.update(record_commit=ref, installer_commit=installer)
        env = {**os.environ, 'REC03_OLD': 'v0.7.7', 'REC03_NEW': 'v0.7.8',
               'REC03_ALLOW_DOCKER': '1', 'REC03_RESOURCE_PROFILE': 'small',
               'REC03_ROOT': str(private), 'REC03_SAME_SCHEMA': '0', 'REC03_INSTALL': 'bundle', 'REC03_INJECT': 'column',
               'REC03_INJECT_TABLE': 'remote_videos', 'REC03_INJECT_COLUMN': 'is_sensitive', 'REC03_INJECT_TYPE': 'BOOLEAN'}
        records = {}
        with (private / 'preflight.log').open('w') as log:
            for tag, schema in (('v0.7.7', 151), ('v0.7.8', 182)):
                record = private / 'state/records' / f'{tag}.json'
                record.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(f'https://raw.githubusercontent.com/yegamble/vidra/{ref}/releases/{tag}.json', timeout=30) as response:
                    record.write_bytes(response.read())
                subprocess.run(['python3', str(ROOT / 'deploy/release-mapping.py'), 'resolve', '--release', tag, '--fetched-record', str(record)], check=True, stdout=log, stderr=log)
                data = json.loads(record.read_text())
                require(data['core_schema_version'] == schema and data['search_schema_version'] == 18, 'candidate schema mismatch')
                records[tag] = data
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
                    records, lambda command: subprocess.check_output(
                        command, cwd='/opt/vidra', env=env, stderr=log, text=True, timeout=60))
            result['phases'][phase] = verdict
            previous[phase] = facts
        result['status'] = 'PASS'
    except Exception as error:
        result['failed_phase'] = phase
        result['failure'] = str(error) if isinstance(error, Failure) else type(error).__name__
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
