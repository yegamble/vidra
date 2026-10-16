#!/usr/bin/env python3
"""Two fresh hosted VMs, synthetic fixtures, real published image/backup bytes."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tarfile

from blank_server_smoke import require
import recovery_release_acceptance as recovery
import release_acceptance as runtime
from sealed_recovery_host import Host, INSTALL
import sealed_recovery_support as support

SCOPE = 'published-image synthetic cross-VM sealed-secret subset'
PROOF_KEYS = {'scope', 'record_commit', 'tool_commit', 'record_hash', 'source_boot',
              'source_stopped', 'catalogue', 'config_hashes', 'script_hashes'}


def record_hash(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def verify_proof(proof, record, record_commit, tool_commit, boot):
    require(set(proof) == PROOF_KEYS and proof['scope'] == SCOPE, 'wrong handoff scope')
    require(proof['record_commit'] == record_commit and proof['tool_commit'] == tool_commit
            and proof['record_hash'] == record_hash(record), 'handoff provenance differs')
    require(proof['source_stopped'] is True and proof['source_boot'] != boot, 'another source VM required')


def restore_config(archive_path, root, expected):
    require(recovery.check_config_archive(archive_path, None) == expected, 'configuration bytes differ')
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        require(len(members) == 2 and all(m.isfile() for m in members)
                and {m.name.removeprefix('./') for m in members} == recovery.CONFIG_MEMBERS, 'invalid config archive')
        for member in members:
            path = root / member.name.removeprefix('./')
            require(not path.exists(), 'existing configuration refused')
            with path.open('xb') as output:
                output.write(archive.extractfile(member).read())
            path.chmod(0o600)


def no_smtp_listener(host):
    container = host.compose('ps', '-q', 'api').strip()
    host.run(['docker', 'exec', container, 'awk', '$2 ~ /:0001$/ && $4 == "0A" {exit 1}',
              '/proc/net/tcp', '/proc/net/tcp6'], 'no-loopback-smtp-listener')


def execute(args, result, hosts):
    require(support.head(support.ROOT) == args.tool_commit and re.fullmatch(r'[0-9a-f]{40}', args.tool_commit),
            'tool commit must be immutable and match checkout')
    record, candidate = support.published(args.record_root, args.release, args.record_commit)
    require(record['core_schema_version'] >= 182, 'candidate must contain sealed OIDC providers')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    support.check_vm(runtime.host_facts(), boot)
    require(not args.stage.exists() and args.stage.is_absolute() and args.stage.parent.resolve() == args.stage.parent,
            'new canonical private stage required')
    args.stage.mkdir(mode=0o700)
    host = Host(args.stage, record, candidate)
    hosts.append(host)
    require(not host.run(['docker', 'ps', '-aq'], 'empty-containers', cwd=args.stage).strip(), 'existing containers refused')
    require(not host.run(['docker', 'volume', 'ls', '-q'], 'empty-volumes', cwd=args.stage).strip(), 'existing volumes refused')
    payload = None
    if args.action == 'restore':
        require(args.handoff and args.handoff_sha and runtime.sha(args.handoff) == args.handoff_sha, 'handoff hash differs')
        payload = support.unpack_handoff(args.handoff, host.private / 'handoff', host.env)
        proof = json.loads((payload / 'proof.json').read_text())
        verify_proof(proof, record, args.record_commit, args.tool_commit, boot)
    result['phase'] = 'published-assets'
    host.install()
    if payload:
        restore_config(payload / 'config.tar.gz', INSTALL, proof['config_hashes'])
        require(host.script_hashes == proof['script_hashes'], 'published scripts differ across hosts')
    else:
        host.configure()
    host.pin_and_check()
    result['phase'] = 'restore' if payload else 'migrations'
    host.compose('up', '-d', 'postgres', 'redis')
    fixture = host.private / 'fixture.json'
    if payload:
        fixture.write_bytes((payload / 'fixture.json').read_bytes())
        fixture.chmod(0o600)
        host.run(['bash', 'deploy/restore.sh', '--yes', str(payload / 'backup.dump.gz')], 'published-restore', timeout=1800)
        result['phase'] = 'restore-ready'
        host.ready()
        no_smtp_listener(host)
        result['phase'] = 'restore-snapshot'
        require(not recovery.differing(proof['catalogue'], host.snapshot()), 'restored catalogue differs')
        result['phase'] = 'restore-verify'
        host.api_fixture('verify', fixture)
        result['phase'] = 'wrong-key-start'
        host.env['MFA_KEY_KEK'] = base64.b64encode(secrets.token_bytes(32)).decode()
        host.compose('up', '-d', '--no-build', '--force-recreate', 'api')
        result['phase'] = 'wrong-key-ready'
        host.ready()
        result['phase'] = 'wrong-key-verify'
        host.api_fixture('wrong-key', fixture)
        result['phase'] = 'original-key-start'
        del host.env['MFA_KEY_KEK']
        host.compose('up', '-d', '--no-build', '--force-recreate', 'api')
        result['phase'] = 'original-key-ready'
        host.ready()
        result['phase'] = 'original-key-verify'
        host.api_fixture('verify', fixture)
        result.update(different_runner_boot=True, empty_destination=True, backup_hash_match=True,
                      schema_and_catalogue_match=True, wrong_key_refused=True, mfa_wrong_code_refused=True,
                      mfa_correct_code_accepted=True, mail_secret_status='ok', oidc_secret_status='ok', oidc_disabled=True)
    else:
        host.compose('run', '--rm', 'migrate')
        host.compose('run', '--rm', 'search-migrate')
        result['phase'] = 'start-services'
        host.compose('up', '-d', '--no-build', 'api', 'search', 'frontend')
        result['phase'] = 'ready'
        host.ready()
        result['phase'] = 'owner-claim'
        require(host.sql('SELECT count(*) FROM users').splitlines()[-1] == '0', 'existing accounts refused')
        no_smtp_listener(host)
        logs = host.compose('logs', '--no-color', 'api')
        tokens = re.findall(r'403 owner_claim_required until claimed\): ([A-Za-z0-9_-]+)', logs)
        require(tokens, 'owner claim token missing')
        result['phase'] = 'api-fixture'
        host.api_fixture('source', fixture, tokens[-1])
        result['phase'] = 'snapshot'
        before = host.snapshot()
        result['phase'] = 'backup'
        log = host.run(['bash', 'deploy/backup.sh'], 'published-backup', timeout=1800)
        dump, config = recovery.parse_backup_done(log)
        require(not recovery.differing(before, host.snapshot()), 'fixture changed during backup')
        config_path = INSTALL / 'backups' / config
        config_hashes = recovery.check_config_archive(config_path, INSTALL)
        host.compose('stop')
        require(not host.compose('ps', '-q').strip(), 'source services still running')
        proof_path = host.private / 'proof.json'
        proof_path.write_text(json.dumps({'scope': SCOPE, 'record_commit': args.record_commit, 'tool_commit': args.tool_commit,
            'record_hash': record_hash(record), 'source_boot': boot, 'source_stopped': True,
            'catalogue': before, 'config_hashes': config_hashes, 'script_hashes': host.script_hashes}))
        support.pack_handoff({'backup.dump.gz': INSTALL / 'backups' / dump, 'config.tar.gz': config_path,
                             'fixture.json': fixture, 'proof.json': proof_path}, args.stage / 'synthetic-handoff.age', host.env)
    host.assert_scripts()
    result.update(status='PASS', phase='complete', external_delivery_blocked=True,
                  release=args.release, record_commit=args.record_commit, tool_commit=args.tool_commit,
                  core_schema=record['core_schema_version'], search_schema=record['search_schema_version'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('source', 'restore'))
    for name in ('release', 'record-commit', 'tool-commit'):
        parser.add_argument('--' + name, required=True)
    for name in ('record-root', 'stage'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--handoff', type=Path)
    parser.add_argument('--handoff-sha')
    args = parser.parse_args()
    new_stage = not args.stage.exists()
    os.umask(0o077)
    result = {'status': 'FAIL', 'scope': SCOPE, 'synthetic_only': True, 'phase': 'preconditions'}
    hosts = []
    try:
        execute(args, result, hosts)
    except Exception:
        try:
            facts = hosts[-1].failure_diagnostics() if hosts else {}
            if facts:
                result['diagnostics'] = facts
        except Exception:
            pass  # Diagnostics must never mask failure or expose exception text.
    if new_stage and (args.stage / 'private').is_dir():
        (args.stage / 'verdict.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
