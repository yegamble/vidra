#!/usr/bin/env python3
"""Recovery acceptance on the frozen v0.6.4 candidate (REC-01/02, OPS-01 subsets).

Runs ON a disposable acceptance host and reuses release_acceptance.Recorder, so
every command, exit and private log is captured exactly as the runtime milestone
captured them. Browser steps live in recovery-release-acceptance.mjs.

Boundaries this module holds by construction:
  * source actions stop and start services but never remove a volume, image,
    container or evidence directory;
  * `restore` runs only on a host with no deployment tree and no containers, so
    restoring over the original destination can never pass as replacement-host
    proof;
  * recovery durations are MEASUREMENTS. No RPO/RTO objective has been approved
    for this candidate, so none is asserted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.request

import release_acceptance as runtime
from blank_server_smoke import require, sha
from runtime_smoke import check_ledger

BASELINE = Path('/root/vidra-v064-runtime')
INSTALL = runtime.INSTALL
# The catalogue #187 fingerprinted across a host reboot, plus the two tables that
# hold the sealed TOTP fixture: a restore that loses them passes every other
# check while silently stripping every account's second factor.
CATALOGUE = ('users', 'channels', 'videos', 'comments', 'playlists', 'playlist_items',
             'channel_follows', 'video_ratings', 'video_tags', 'video_chapters',
             'streaming_playlists', 'video_files', 'captions', 'user_mfa', 'mfa_recovery_codes')
CONFIG_MEMBERS = {'env/production.env', 'deploy/Caddyfile.local'}
FAULT_SERVICES = ('postgres', 'redis', 'search')


def fingerprint_sql(table):
    require(re.fullmatch(r'[a-z_]+', table), 'invalid table name')
    return (f"SELECT count(*)||'|'||md5(COALESCE(string_agg(r::text,E'\\n' ORDER BY r::text),'')) "
            f"FROM (SELECT to_jsonb(t) AS r FROM {table} t) s")


# search.documents carries reconcile timestamps that a healthy sweep rewrites, so
# only the fields a search result depends on are compared.
SEARCH_SQL = ("SELECT count(*)||'|'||md5(COALESCE(string_agg(video_id::text||':'||title||':'||eligible::text,"
              "E'\\n' ORDER BY video_id::text),'')) FROM search.documents")


def fingerprint(run):
    rows = {table: run.sql(fingerprint_sql(table)) for table in CATALOGUE}
    rows['search.documents'] = run.sql(SEARCH_SQL)
    return rows


def differing(before, after):
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def parse_backup_done(log):
    matches = re.findall(r'done — database (vidra-\d{8}T\d{6}Z\.dump\.gz), config (vidra-config-\d{8}T\d{6}Z\.tar\.gz)', log)
    require(len(matches) == 1, 'backup did not report exactly one finished dump/config pair')
    dump, config = matches[0]
    require(dump.removeprefix('vidra-').removesuffix('.dump.gz') == config.removeprefix('vidra-config-').removesuffix('.tar.gz'),
            'dump and config archive stamps differ')
    return dump, config


def check_config_archive(path, live_root):
    with tarfile.open(path) as archive:
        members = {m.name.removeprefix('./'): m for m in archive.getmembers() if m.isfile()}
        require(set(members) == CONFIG_MEMBERS, f'config archive members {sorted(members)}')
        hashes = {}
        for name, member in members.items():
            data = archive.extractfile(member).read()
            hashes[name] = hashlib.sha256(data).hexdigest()
            if live_root is not None:
                require(hashes[name] == sha(live_root / name), f'{name}: archive differs from the live file')
    return hashes


def http(path, timeout=5):
    started = time.time()
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080' + path, timeout=timeout) as response:
            return {'path': path, 'status': response.status, 'body': response.read(2048).decode(errors='replace'),
                    'at': started}
    except urllib.error.HTTPError as error:
        return {'path': path, 'status': error.code, 'body': error.read(2048).decode(errors='replace'), 'at': started}
    except (OSError, urllib.error.URLError) as error:
        return {'path': path, 'status': None, 'error': type(error).__name__, 'at': started}


def api_identity(run):
    cid = run.compose('ps', '-q', 'api').strip()
    require(cid, 'api container missing')
    info = json.loads(run.run(['docker', 'inspect', cid], 'inspect-api'))[0]
    return {'id': info['Id'], 'started_at': info['State']['StartedAt'], 'restart_count': info['RestartCount']}


def snapshot(run, candidate, with_images=True):
    result = {'at': time.time(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'catalogue': fingerprint(run), 'ledgers': {}, 'api': api_identity(run)}
    if with_images:
        result['runtime'] = runtime.runtime_snapshot(run, candidate)
    for table, spec in json.loads((BASELINE / 'expected-ledgers.json').read_text()).items():
        actual = run.sql(f'SELECT version, dirty FROM {table}')
        check_ledger(actual, spec['version'])
        result['ledgers'][table] = actual
    return result


def wait(check, timeout, pause=2):
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        require(time.monotonic() < deadline, 'timed out waiting for recovery')
        time.sleep(pause)


def fault(run, candidate, service, result):
    require(service in FAULT_SERVICES, 'unsupported fault service')
    probes = ('/readyz', '/api/v1/videos?limit=1', '/api/v1/videos/search?q=recovery')
    result['before'] = snapshot(run, candidate)
    result['before_probes'] = [http(p) for p in probes]
    require(result['before_probes'][0]['status'] == 200, 'stack not ready before the fault')
    result['stopped_at'] = time.time()
    run.compose('stop', service)
    time.sleep(10)
    result['during_probes'] = [http(p) for p in probes]
    result['started_at'] = time.time()
    run.compose('start', service)
    runtime.wait_for_runtime(run)
    ready = wait(lambda: (p := http('/readyz'))['status'] == 200 and p, 300)
    result['ready_probe'] = ready
    result['recovery_seconds'] = round(ready['at'] - result['started_at'], 3)
    result['after_probes'] = [http(p) for p in probes]
    result['after'] = snapshot(run, candidate)
    # Recovery must come from the process reconnecting, not from someone (or
    # Docker's restart policy) replacing the api container behind the probe.
    require(result['after']['api'] == result['before']['api'], 'api container restarted during the fault')
    changed = differing(result['before']['catalogue'], result['after']['catalogue'])
    require(not changed, f'{service} outage changed persisted state: {changed}')
    result['checks'][f'{service}_outage_recovered_without_api_restart'] = 'PASS'


def backup(run, candidate, stage, result):
    result['before'] = snapshot(run, candidate)
    log = run.run(['bash', 'deploy/backup.sh'], 'backup', timeout=1800)
    result['after'] = snapshot(run, candidate)
    changed = differing(result['before']['catalogue'], result['after']['catalogue'])
    require(not changed, f'writes landed during the backup, so the recovered data point is ambiguous: {changed}')
    dump, config = parse_backup_done(log)
    backups = INSTALL / 'backups'
    marker = (backups / 'last_success').read_text().split()
    require(len(marker) == 2 and marker[1] == dump, 'last_success does not name this dump')
    for name in (dump, config):
        require((backups / name).stat().st_mode & 0o077 == 0, f'{name} is readable beyond its owner')
    listing = run.run(['sh', '-c', f'gzip -dc {backups / dump} | docker exec -i "$(bash deploy/compose.sh ps -q postgres)" pg_restore -l'],
                      'backup-list')
    entries = {line for line in listing.splitlines() if not line.startswith(';')}
    for needle in ('SCHEMA - search', 'TABLE DATA public users', 'TABLE DATA public user_mfa',
                   'TABLE DATA public schema_migrations', 'TABLE DATA public vidra_search_migrations',
                   'TABLE DATA search documents'):
        require(any(needle in entry for entry in entries), f'dump lacks {needle}')
    result['config_members_sha256'] = check_config_archive(backups / config, INSTALL)
    handoff = stage / 'private' / 'handoff'
    handoff.mkdir(mode=0o700)
    for name in (dump, config):
        shutil.copy2(backups / name, handoff / name)
    result['handoff'] = {name: sha(handoff / name) for name in (dump, config)}
    result['data_point'] = {'catalogue': result['after']['catalogue'], 'ledgers': result['after']['ledgers'],
                            'marker': ' '.join(marker)}
    result['media'] = ('STORAGE_BACKEND=s3: media stays in the dedicated test bucket by design and is not in '
                       'either archive; restore.sh verify-blobs is the media reconciliation.')
    result['checks']['backup_contains_both_schemas_ledgers_mfa_and_config'] = 'PASS'


def check_failed_backup(before, after, output):
    """The shipped contract, not a stricter invented one: backup.sh writes to
    `.part` and renames only after pg_restore -l passes, so a failed run may leave
    its private `.part` (tests/backup_test.py asserts exactly that) but must not
    publish a dump or config archive, touch an existing file, or advance
    last_success — the marker `vidra doctor` trusts."""
    changed = sorted(name for name in before if after.get(name) != before[name])
    require(not changed, f'a failed backup changed or removed existing files: {changed}')
    new = sorted(set(after) - set(before))
    require(all(name.endswith('.part') for name in new), f'a failed backup published files: {new}')
    require('done — database' not in output, 'failed backup reported success')
    return new


def failed_backup(run, result):
    backups = INSTALL / 'backups'
    before = {p.name: sha(p) for p in backups.iterdir() if p.is_file()}
    env = dict(run.env, POSTGRES_DB='vidra_recovery_fault_missing')
    output = run.run(['bash', 'deploy/backup.sh'], 'failed-backup', env=env, expected=1)
    after = {p.name: sha(p) for p in backups.iterdir() if p.is_file()}
    result['partial_files_left'] = check_failed_backup(before, after, output)
    for name in result['partial_files_left']:
        require((backups / name).stat().st_mode & 0o077 == 0, f'{name} is readable beyond its owner')
    result['failure_tail'] = output.strip().splitlines()[-3:]
    result['checks']['failed_backup_exits_nonzero_and_advertises_nothing'] = 'PASS'


def source_loss(run, candidate, result):
    result['before'] = snapshot(run, candidate)
    result['stopped_at'] = time.time()
    run.compose('stop')
    left = run.compose('ps', '-q').split()
    require(not left, 'containers still running after the simulated host loss')
    result['checks']['source_stack_stopped_volumes_retained'] = 'PASS'


def restore(run, candidate, stage, handoff, source_loss_result, result):
    installer = BASELINE / 'install.sh'
    # The same blank-host guard the runtime milestone used: native Ubuntu 24.04
    # AMD64, root in a systemd VM, and no deployment tree, CLI or container
    # runtime. A populated original destination can never pass as a replacement.
    result['before'] = runtime.host_facts()
    runtime.check_host(result['before'])
    run.run(['ss', '-lntup'], 'before-listeners', cwd=stage)
    files = {p.name: p for p in handoff.iterdir()}
    dumps = [n for n in files if n.endswith('.dump.gz')]
    configs = [n for n in files if n.startswith('vidra-config-')]
    require(len(dumps) == 1 and len(configs) == 1, 'handoff must hold one dump and one config archive')
    expected = json.loads((handoff.parent / 'backup-result.json').read_text())
    require(expected['status'] == 'PASS', 'source backup did not pass')
    for name, digest in expected['handoff'].items():
        require(sha(files[name]) == digest, f'{name}: transferred bytes differ from the source backup')
    result['timeline'] = {'source_stopped_at': source_loss_result['stopped_at'], 'install_started_at': time.time()}
    run.run(['sh', str(installer), '--yes', '--ref', candidate['tag'], '--dir', str(INSTALL)], 'install', cwd=stage)
    require(not (INSTALL / '.git').exists(), 'installer used a checkout, not the released bundle')
    manifest = (INSTALL / 'vidra-bundle.manifest').read_text().splitlines()
    require(f"tag={candidate['tag']}" in manifest and f"core_commit={candidate['repositories']['vidra-core']['revision']}" in manifest,
            'installed bundle is not the frozen candidate')
    require(sha('/usr/local/bin/vidra') == candidate['assets'][f"vidra_{candidate['tag']}_linux_amd64"]['sha256'], 'CLI drift')
    require(not (INSTALL / 'env/production.env').exists(), 'installer wrote configuration before the restore')
    result['timeline']['config_restore_at'] = time.time()
    # deploy/README.md "Disaster recovery", step 3, verbatim: configuration FIRST.
    run.run(['tar', '-xzf', str(handoff / configs[0]), '-C', str(INSTALL)], 'restore-config')
    require(check_config_archive(handoff / configs[0], INSTALL) == expected['config_members_sha256'], 'restored config differs')
    # The same, and only, adaptation every v0.6.4 acceptance deployment used:
    # the six application image references pinned to the frozen digests.
    # Deployment scripts must still match the released bundle byte for byte.
    for name, digest in json.loads((BASELINE / 'frozen-deploy-hashes.json').read_text()).items():
        require(sha(INSTALL / name) == digest, f'installed deployment source differs: {name}')
    shutil.copyfile(BASELINE / 'pinned-prod.yml', INSTALL / 'docker-compose.prod.yml')
    result['deployment_adaptation'] = 'six application image references replaced with frozen digests; scripts unchanged'
    run.compose('up', '-d', 'postgres')
    wait(lambda: 'healthy' in run.run(['docker', 'inspect', '--format', '{{.State.Health.Status}}',
                                        run.compose('ps', '-q', 'postgres').strip()], 'postgres-health'), 300)
    result['timeline']['restore_started_at'] = time.time()
    restore_log = run.run(['bash', 'deploy/restore.sh', '--yes', str(handoff / dumps[0])], 'restore', timeout=3600)
    result['timeline']['restore_finished_at'] = time.time()
    result['verify_blobs_lines'] = [l for l in restore_log.splitlines() if 'verify-blobs' in l or 'missing' in l.lower()][-10:]
    run.run(['bash', 'deploy/deploy.sh'], 'deploy', timeout=3600)
    runtime.wait_for_runtime(run)
    result['timeline']['ready_at'] = wait(lambda: (p := http('/readyz'))['status'] == 200 and p['at'], 600)
    result['after'] = snapshot(run, candidate)
    changed = differing(expected['data_point']['catalogue'], result['after']['catalogue'])
    require(not changed, f'restored catalogue differs from the backup data point: {changed}')
    require(result['after']['ledgers'] == expected['data_point']['ledgers'], 'restored ledgers differ')
    t = result['timeline']
    result['measured'] = {
        'source_loss_to_ready_seconds': round(t['ready_at'] - t['source_stopped_at'], 3),
        'install_to_ready_seconds': round(t['ready_at'] - t['install_started_at'], 3),
        'restore_script_seconds': round(t['restore_finished_at'] - t['restore_started_at'], 3),
        'objective': 'none approved for this candidate; measurement only'}
    result['checks']['replacement_host_restore_matches_backup_data_point'] = 'PASS'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'fault', 'backup', 'failed-backup', 'source-loss', 'restore'])
    parser.add_argument('--stage', type=Path, required=True, help='new attempt directory per action')
    parser.add_argument('--service', choices=FAULT_SERVICES)
    parser.add_argument('--handoff', type=Path, help='restore: directory holding the transferred dump/config')
    parser.add_argument('--source-loss', type=Path, help='restore: source-loss result.json')
    parser.add_argument('--acknowledge', help='restore: must be "replacement-host"')
    args = parser.parse_args()
    os.umask(0o077)
    stage = args.stage.resolve()
    require(not stage.exists(), 'use a new stage per attempt; failed evidence is retained')
    stage.mkdir(parents=True, mode=0o700)
    run = runtime.Recorder(stage)
    result = {'status': 'UNVERIFIED', 'action': args.action, 'service': args.service,
              'started_at': time.time(), 'checks': {}}
    try:
        candidate = json.loads((BASELINE / 'candidate.json').read_text())
        if args.action == 'snapshot':
            result['snapshot'] = snapshot(run, candidate)
        elif args.action == 'fault':
            fault(run, candidate, args.service, result)
        elif args.action == 'backup':
            backup(run, candidate, stage, result)
        elif args.action == 'failed-backup':
            failed_backup(run, result)
        elif args.action == 'source-loss':
            source_loss(run, candidate, result)
        else:
            require(args.acknowledge == 'replacement-host', 'explicit replacement-host acknowledgement required')
            restore(run, candidate, stage, args.handoff.resolve(),
                    json.loads(args.source_loss.read_text()), result)
        result['status'] = 'PASS'
    except Exception as error:  # every failure is recorded, never swallowed
        result['status'] = 'FAIL'
        result['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        result['finished_at'] = time.time()
        runtime.save(stage / 'result.json', result)
    print(json.dumps({'status': result['status'], 'checks': result['checks']}))


if __name__ == '__main__':
    main()
