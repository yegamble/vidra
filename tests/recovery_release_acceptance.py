#!/usr/bin/env python3
"""Recovery acceptance on a frozen release candidate (REC-01/02, OPS-01 subsets).

Runs ON a disposable acceptance host and reuses release_acceptance.Recorder, so
every command, exit and private log is captured exactly as the runtime milestone
captured them. Browser steps live in recovery-release-acceptance.mjs.

`--baseline` is the prepared runtime stage of the candidate under drill: its
`candidate.json` names the release, and its `expected-ledgers.json`,
`install.sh`, `frozen-deploy-hashes.json` and `pinned-prod.yml` are what the
drill installs and asserts against. It was hard-wired to the v0.6.4 stage, which
is now only the DEFAULT, so a v0.6.5 drill passes
`--baseline /root/vidra-v065-runtime`. Pass the same value to the browser half
via VIDRA_BASELINE.

The source actions behave exactly as they did for v0.6.4 when every flag is
defaulted. `restore` does NOT: it now requires the backup and source-loss
records it consumes to name the release they were taken on, and the archived
v0.6.4 results predate that stamping. Restoring from them means re-running the
source actions on this harness — deliberate, since the v0.6.4 drill is closed.

Boundaries this module holds by construction:
  * source actions stop and start services but never remove a volume, image,
    container or evidence directory;
  * `restore` runs only on a host with no deployment tree and no containers, so
    restoring over the original destination can never pass as replacement-host
    proof;
  * recovery durations are MEASUREMENTS. No RPO/RTO objective has been approved
    for this candidate, so none is asserted;
  * the catalogue a drill compares is a function of the CANDIDATE's own frozen
    schema version, and a candidate newer than the catalogue's audit is REFUSED
    rather than certified against tables nobody has classified.
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
from blank_server_smoke import require, sha, validate_candidate
from runtime_smoke import check_ledger

DEFAULT_BASELINE = Path('/root/vidra-v064-runtime')
INSTALL = runtime.INSTALL
CONFIG_MEMBERS = {'env/production.env', 'deploy/Caddyfile.local'}
FAULT_SERVICES = ('postgres', 'redis', 'search')

# --- the catalogue a drill proves the restored/rebooted database still holds ---
#
# Each entry is `table: (core schema version that CREATED it, volatile columns)`.
#
# A fingerprint is `count(*)` plus an order-independent md5 over the rows'
# `to_jsonb` MINUS the volatile keys. Deleting keys from the whole row — rather
# than SELECTing a hand-written column list — is what keeps the assertion
# fail-closed: every column NOBODY excluded stays in the hash, so a restore that
# drops one is caught, and a column a later migration adds is covered the day it
# lands. Naming a column here is therefore a WRITTEN DECISION that a background
# worker rewrites it, and that comparing it would fail a drill between backup
# time and post-restore time for a reason that predicts nothing.
#
# The version is what makes the catalogue a function of the CANDIDATE rather
# than of the host (`catalogue_for`): the same two harness files drill a v0.6.x
# stage that has none of the 0147-0150 tables and a v0.7.5 stage that must have
# all of them. Fingerprinting "whatever tables happen to exist" would pass a
# restore that lost every one of them, which is exactly what used to happen.
PRE_EXISTING = 0  # in every candidate this harness can drill (v0.6.4 = core schema 144)
CATALOGUE = {
    # The catalogue #187 fingerprinted across a host reboot, plus the two tables
    # that hold the sealed TOTP fixture: a restore that loses them passes every
    # other check while silently stripping every account's second factor. Whole
    # rows — the drill fixture is quiesced and nothing rewrites these unattended.
    'users': (PRE_EXISTING, ()),
    'channels': (PRE_EXISTING, ()),
    'videos': (PRE_EXISTING, ()),
    'comments': (PRE_EXISTING, ()),
    'playlists': (PRE_EXISTING, ()),
    'playlist_items': (PRE_EXISTING, ()),
    'channel_follows': (PRE_EXISTING, ()),
    'video_ratings': (PRE_EXISTING, ()),
    'video_tags': (PRE_EXISTING, ()),
    'video_chapters': (PRE_EXISTING, ()),
    'streaming_playlists': (PRE_EXISTING, ()),
    'video_files': (PRE_EXISTING, ()),
    'captions': (PRE_EXISTING, ()),
    'user_mfa': (PRE_EXISTING, ()),
    'mfa_recovery_codes': (PRE_EXISTING, ()),
    # 0147. Comments this instance's own users authored on REMOTE videos. The
    # home instance hosts them, so a lost row is a user's content gone — there
    # is no origin to re-fetch it from. The four federation columns are mirrored
    # onto the row from the delivery queue by
    # SetAuthoredRemoteCommentDeliveryState, which DrainDeliveries calls on every
    # attempt: a replacement host re-drains against origins it may not reach, so
    # a pending row can legitimately be 'failed' with a higher attempts count by
    # the time the restored catalogue is read.
    'authored_remote_comments': (147, ('delivery_state', 'last_error', 'attempts', 'updated_at')),
    # 0148. The singleton desired-node-configuration document: operator intent,
    # written only by an admin save (UpdateIPFSControlConfig moves config,
    # revision, policy_active, updated_by and updated_at in one statement), never
    # by a tick. Whole row. Note it is also created LAZILY by the first read that
    # finds none, so "absent in the dump, present afterwards" means the drill
    # touched managed IPFS after the backup, not that a restore lost anything.
    'ipfs_control_config': (148, ()),
    # 0148. Requested apply/restart operations. Who asked for what, against which
    # config revision and when, is durable — HTTP-retry idempotency depends on
    # the row surviving — but the five state-machine columns are rewritten by the
    # leader's ObserveIPFSControlOperation on every tick that finds work.
    'ipfs_control_operations': (148, ('state', 'last_error_code', 'attempts',
                                      'next_attempt_at', 'updated_at')),
    # 0149, extended by 0150. Pure admission accounting plus a maintenance lease:
    # admission UPDATEs the byte and claim counters, the cleanup sweep takes and
    # releases the lease and pushes measure_after to now(). No column here is
    # content, so the fingerprint asserts only the singleton row 0150 seeds —
    # that it is there, and that there is exactly one. The table going missing
    # altogether is still caught, by name, before any fingerprint is taken.
    'ipfs_capacity': (149, ('reserved_bytes', 'active_claims', 'measure_after', 'cleanup_pending',
                            'maintenance_token', 'maintenance_until', 'maintenance_host_sequence',
                            'maintenance_config_revision')),
    # 0150. A queue, but every row is a durable obligation: a CID copied into the
    # node that must still be unpinned. Losing one leaks that storage for good,
    # so rows are compared whole. Rows are only inserted (RecordIPFSReturnedCopy)
    # and deleted (FinishIPFSCopyCleanup), never rewritten in place, so a
    # quiesced fixture cannot drift here.
    'ipfs_copy_cleanup': (150, ()),
}

# Tables a migration creates that the drill deliberately does NOT fingerprint,
# as `table: (core schema version that created it, why)`. Empty today: every
# table 0147-0150 added carries something a restore must reproduce. It exists so
# that "pure ephemeral state, nothing worth asserting" is a diff-visible
# decision with a reason attached, never a silent omission.
EXCLUDED_TABLES = {}

# What "audited" means: one line per core schema version from the floor upward,
# naming the tables that version's migration CREATEs (an empty tuple when it
# creates none), read out of vidra-core's `migrations/<version>_*.up.sql` at the
# newest release this repo records. The ceiling is DERIVED from this map, so the
# audit cannot be advanced by editing a number — landing a release with a newer
# schema forces a new line here (the rot guard in the test module fails until it
# exists), and every table on that line must then land in CATALOGUE or in
# EXCLUDED_TABLES with a reason. The floor is where the audit starts: the fifteen
# tables above were curated by hand for the #187 reboot catalogue and the v0.6.4
# MFA drill and predate any inventory.
CATALOGUE_AUDIT_FLOOR = 147
TABLES_ADDED = {
    147: ('authored_remote_comments',),
    148: ('ipfs_control_config', 'ipfs_control_operations'),
    149: ('ipfs_capacity',),
    150: ('ipfs_copy_cleanup',),
}
CATALOGUE_AUDITED_THROUGH = max(TABLES_ADDED)
IDENTIFIER = re.compile(r'[a-z_]+')


def load_candidate(baseline):
    """The baseline names the release under drill; nothing else may.

    The drill installs from this manifest and asserts every image against it, so
    it gets the same A01 validation `release_acceptance` applies — a manifest of
    a release whose own verification did not pass is not a candidate. Read here
    rather than at each use so a baseline holding no manifest, or a bad one,
    fails at the first line of the action instead of KeyError-ing mid-restore.
    """
    path = Path(baseline) / 'candidate.json'
    candidate = json.loads(path.read_text())
    try:
        validate_candidate(candidate)
    except ValueError as error:
        raise ValueError(f'{path}: {error}') from error
    return candidate


def check_recorded_tag(name, record, candidate):
    """Evidence a restore consumes must come from the release it rebuilds.

    A dump taken on one candidate, restored onto a host installed from another,
    then passes every downstream comparison — because the expected catalogue and
    ledgers come from that same wrong evidence. Every action records
    `candidate_tag`; a record without one is refused, never assumed to match.
    The archived v0.6.4 source results predate the stamping, so the message says
    so: a real refusal must not read as a harness bug.
    """
    recorded = record.get('candidate_tag')
    remedy = '' if recorded else (' (records written before candidate_tag stamping cannot be restored; '
                                  're-run the source actions on this harness)')
    require(recorded == candidate['tag'],
            f"{name} was recorded on {recorded or 'an unrecorded release'}, not {candidate['tag']}{remedy}")


def identifier(name, kind='table'):
    require(isinstance(name, str) and IDENTIFIER.fullmatch(name), f'invalid {kind} name')
    return name


def fingerprint_sql(table, volatile=()):
    """count(*) plus an order-independent md5 over one table's stable content.

    `to_jsonb(t)` is the WHOLE row, so a column missing from a restored table
    changes the hash. The volatile keys are deleted from that jsonb rather than
    replaced by a hand-written column list, which is what keeps the property for
    every column nobody excluded — including ones a later migration adds. A
    table with nothing volatile produces exactly the SQL the v0.6.x drills
    recorded, so this change moves no existing fingerprint.
    """
    identifier(table)
    keys = ''
    if volatile:
        keys = " - ARRAY[" + ','.join(f"'{identifier(c, 'column')}'" for c in volatile) + "]::text[]"
    return (f"SELECT count(*)||'|'||md5(COALESCE(string_agg(r::text,E'\\n' ORDER BY r::text),'')) "
            f"FROM (SELECT to_jsonb(t){keys} AS r FROM {table} t) s")


def expected_ledgers(baseline):
    return json.loads((Path(baseline) / 'expected-ledgers.json').read_text())


def core_schema_version(ledgers):
    """Which core schema the CANDIDATE embeds, per the stage's frozen ledgers.

    `release_acceptance prepare` computes expected-ledgers.json from the frozen
    source migrations, so this is the release's own number rather than a literal
    somebody has to keep current — and, deliberately, not the live database's,
    which is the very thing a restore is being asked to reproduce.
    """
    spec = ledgers.get('schema_migrations')
    version = spec.get('version') if isinstance(spec, dict) else None
    require(isinstance(version, int),
            'expected-ledgers.json names no core schema_migrations version, so the tables this '
            'candidate requires cannot be determined')
    return version


def catalogue_for(core_version):
    """The tables THIS candidate's schema requires, and what to leave out of each.

    Fail-closed at both ends. An older candidate is not asked for tables its
    schema never had (that would fail a correct drill); a candidate newer than
    the audit is REFUSED rather than drilled against a catalogue that has never
    heard of its migrations — certifying "the restored database is the same
    database" while silently ignoring everything a new migration added is the
    failure this catalogue exists to prevent, and it is not detectable after the
    fact from the evidence a drill produces.
    """
    require(core_version <= CATALOGUE_AUDITED_THROUGH,
            f'candidate core schema {core_version} is newer than this catalogue, which is audited '
            f'through {CATALOGUE_AUDITED_THROUGH}: read vidra-core migrations '
            f'{CATALOGUE_AUDITED_THROUGH + 1:04d}..{core_version:04d}, add a TABLES_ADDED line per '
            'version, and catalogue or explicitly exclude every table they CREATE before drilling')
    return {table: volatile for table, (since, volatile) in CATALOGUE.items() if since <= core_version}


def unclassified_tables(added=None):
    """Tables a migration CREATEs that neither the catalogue nor the exclusions know."""
    return sorted(table for tables in (TABLES_ADDED if added is None else added).values()
                  for table in tables if table not in CATALOGUE and table not in EXCLUDED_TABLES)


def missing_tables(expected, present):
    """Tables the candidate's schema requires that the database does not have.

    "Exists and empty" is a PASS — an always-empty table (managed IPFS is off on
    a drill host) still proves the table survived — so emptiness must never read
    as absence and absence must never read as emptiness. psql's own `relation
    does not exist` reaches the operator only as `exit 1; see 0NN-*.log`, so the
    table has to be named here or it is named nowhere.
    """
    return sorted(set(expected) - set(present))


def check_catalogue_present(run, tables, core_version):
    names = ','.join(f"'{identifier(table)}'" for table in tables)
    found = run.sql("SELECT COALESCE(string_agg(c.relname, ',' ORDER BY c.relname), '') FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' "
                    f"AND c.relkind IN ('r', 'p') AND c.relname IN ({names})")
    missing = missing_tables(tables, found.split(',') if found else [])
    require(not missing, f'core schema {core_version} requires tables this database does not have: '
                         + ', '.join(missing))


# search.documents carries reconcile timestamps that a healthy sweep rewrites, so
# only the fields a search result depends on are compared.
SEARCH_SQL = ("SELECT count(*)||'|'||md5(COALESCE(string_agg(video_id::text||':'||title||':'||eligible::text,"
              "E'\\n' ORDER BY video_id::text),'')) FROM search.documents")


def fingerprint(run, core_version):
    tables = catalogue_for(core_version)
    # Existence first, and in one query: a table the schema requires but the
    # database lacks must fail by NAME, before a fingerprint query turns it into
    # an anonymous psql exit 1 buried in a private log.
    check_catalogue_present(run, tables, core_version)
    rows = {table: run.sql(fingerprint_sql(table, volatile)) for table, volatile in tables.items()}
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


def snapshot(run, candidate, baseline, with_images=True):
    # One read of the frozen ledgers serves both halves of the snapshot: which
    # tables this candidate's schema requires, and which versions it must be at.
    ledgers = expected_ledgers(baseline)
    result = {'at': time.time(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'catalogue': fingerprint(run, core_schema_version(ledgers)), 'ledgers': {},
              'api': api_identity(run)}
    if with_images:
        result['runtime'] = runtime.runtime_snapshot(run, candidate)
    for table, spec in ledgers.items():
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


def fault(run, candidate, baseline, service, result):
    require(service in FAULT_SERVICES, 'unsupported fault service')
    probes = ('/readyz', '/api/v1/videos?limit=1', '/api/v1/videos/search?q=recovery')
    result['before'] = snapshot(run, candidate, baseline)
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
    result['after'] = snapshot(run, candidate, baseline)
    # Recovery must come from the process reconnecting, not from someone (or
    # Docker's restart policy) replacing the api container behind the probe.
    require(result['after']['api'] == result['before']['api'], 'api container restarted during the fault')
    changed = differing(result['before']['catalogue'], result['after']['catalogue'])
    require(not changed, f'{service} outage changed persisted state: {changed}')
    result['checks'][f'{service}_outage_recovered_without_api_restart'] = 'PASS'


def backup(run, candidate, baseline, stage, result):
    result['before'] = snapshot(run, candidate, baseline)
    log = run.run(['bash', 'deploy/backup.sh'], 'backup', timeout=1800)
    result['after'] = snapshot(run, candidate, baseline)
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


def source_loss(run, candidate, baseline, result):
    result['before'] = snapshot(run, candidate, baseline)
    result['stopped_at'] = time.time()
    run.compose('stop')
    left = run.compose('ps', '-q').split()
    require(not left, 'containers still running after the simulated host loss')
    # `compose stop` removes no volume, but nothing here enumerates them, so the
    # check claims only what it asserts. Renamed after the v0.6.4 run; that
    # evidence keeps the earlier key `source_stack_stopped_volumes_retained`.
    result['checks']['source_stack_stopped_no_container_left'] = 'PASS'


def restore(run, candidate, baseline, stage, handoff, source_loss_result, result):
    installer = baseline / 'install.sh'
    check_recorded_tag('source-loss evidence', source_loss_result, candidate)
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
    # The dump about to be restored was produced by that backup, onto a host
    # this action is about to install from `candidate`; a dump from another
    # release would be restored under the wrong images and still match the
    # catalogue it was taken with.
    check_recorded_tag('source backup', expected, candidate)
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
    # The same, and only, adaptation every acceptance deployment since v0.6.4
    # has used: the six application image references pinned to the frozen
    # digests — of the baseline's candidate, not of some other release.
    # Deployment scripts must still match the released bundle byte for byte.
    for name, digest in json.loads((baseline / 'frozen-deploy-hashes.json').read_text()).items():
        require(sha(INSTALL / name) == digest, f'installed deployment source differs: {name}')
    shutil.copyfile(baseline / 'pinned-prod.yml', INSTALL / 'docker-compose.prod.yml')
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
    result['after'] = snapshot(run, candidate, baseline)
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


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'fault', 'backup', 'failed-backup', 'source-loss', 'restore'])
    parser.add_argument('--stage', type=Path, required=True, help='new attempt directory per action')
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE,
                        help='prepared runtime stage of the candidate under drill (default: the v0.6.4 stage)')
    parser.add_argument('--service', choices=FAULT_SERVICES)
    parser.add_argument('--handoff', type=Path, help='restore: directory holding the transferred dump/config')
    parser.add_argument('--source-loss', type=Path, help='restore: source-loss result.json')
    parser.add_argument('--acknowledge', help='restore: must be "replacement-host"')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    baseline = args.baseline.resolve()
    os.umask(0o077)
    stage = args.stage.resolve()
    require(not stage.exists(), 'use a new stage per attempt; failed evidence is retained')
    stage.mkdir(parents=True, mode=0o700)
    run = runtime.Recorder(stage)
    result = {'status': 'UNVERIFIED', 'action': args.action, 'service': args.service,
              'baseline': str(baseline), 'started_at': time.time(), 'checks': {}}
    try:
        candidate = load_candidate(baseline)
        # Every action stamps the release it ran on, so the records `restore`
        # consumes can be checked against the release it is rebuilding.
        result['candidate_tag'] = candidate['tag']
        if args.action == 'snapshot':
            result['snapshot'] = snapshot(run, candidate, baseline)
        elif args.action == 'fault':
            fault(run, candidate, baseline, args.service, result)
        elif args.action == 'backup':
            backup(run, candidate, baseline, stage, result)
        elif args.action == 'failed-backup':
            failed_backup(run, result)
        elif args.action == 'source-loss':
            source_loss(run, candidate, baseline, result)
        else:
            require(args.acknowledge == 'replacement-host', 'explicit replacement-host acknowledgement required')
            restore(run, candidate, baseline, stage, args.handoff.resolve(),
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
