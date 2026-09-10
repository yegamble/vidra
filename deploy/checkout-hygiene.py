#!/usr/bin/env python3
"""Refuse checkout drift before Git writes; keep manual/rollback env copies private."""
import argparse
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


# A copy of an env file holds the same secrets as the original. Match on the
# SHAPE of a copy rather than a short list of suffixes: the previous pattern
# read .env.bak but not .env.backup, .env.bak2, a vim .env.swp or a
# date-stamped .env.2026-09-10, all of which a human types and all of which
# hold live credentials. Templates and framework config are not copies --
# .env.example, .env.template and Next.js's .env.local must stay legal -- so a
# copy word must end the name or be followed by a separator: .env.template is
# not a "temp" copy.
ENV_COPY = r'bak|backup|old|orig|save|saved|copy|prev|previous|tmp|temp'
ENV_BACKUP = re.compile(
    rf'\.env(?:~$|\.sw[a-z]$|\.(?:{ENV_COPY})\d*(?:[.-][\w.-]*)?$|\.\d[\w.-]*$)',
    re.IGNORECASE)


def check(root, env_backups='fatal'):
    """Report every finding at once, and only stop what is actually stopped.

    Severity is not a style choice, it is which failure the finding predicts:

    * Metadata the invoking user cannot write is always fatal. deploy.sh AND
      rollback.sh both fetch and check out the nested repositories, so such a
      tree fails the run anyway -- naming the repair here beats a raw git error
      half-way through a rollback that has already rewritten the tag pins.
    * A stray environment backup cannot affect a rollback, which commits
      nothing. rollback.sh therefore passes 'warn': a hygiene lint must never
      be the reason an operator cannot restore service. deploy.sh keeps it
      fatal, because a deploy is the moment to fix the host.

    Every finding is collected rather than raised on sight. A tree with 74
    foreign-owned objects should cost one repair, not 74 preflight runs.
    """
    if env_backups not in ('fatal', 'warn'):
        raise ValueError(f"env_backups must be 'fatal' or 'warn', not {env_backups!r}")
    root = Path(root).resolve()
    fatal, warnings = [], []
    # Inspect every checkout before fetching ANY of them. Root can otherwise
    # fetch successfully and leave the next deployment unable to write objects.
    for repo in [root, *(root / n for n in ('vidra-core', 'vidra-user', 'vidra-search'))]:
        if not (repo / '.git').exists():
            continue  # Release bundles intentionally have no Git metadata.
        owner = repo.stat().st_uid
        user = pwd.getpwuid(owner).pw_name
        if os.geteuid() != owner:
            raise ValueError(f'Run deployment as checkout owner {user}: '
                             f'sudo -u {shlex.quote(user)} -- ./deploy/deploy.sh')
        dirs = subprocess.check_output(
            ['git', '-C', str(repo), 'rev-parse', '--path-format=absolute',
             '--git-dir', '--git-common-dir'], text=True).splitlines()
        for metadata in set(dirs):
            paths = [Path(metadata)]
            for directory, children, files in os.walk(metadata, onerror=fail_walk):
                paths.extend(Path(directory) / n for n in children + files)
            foreign = [p for p in paths if p.lstat().st_uid != owner]
            if foreign:
                fatal.append(describe_owner(foreign, user, metadata))
    strays, unreadable = [], []
    # NOT fail_walk. A directory this user cannot read is a gap in the scan, not
    # a reason to abort: refusing to roll back because some unrelated directory
    # is mode 000 is the same inversion as refusing over a stray file. The gap
    # is reported at the severity of the scan it belongs to, so a deploy still
    # stops and a rollback still runs.
    for directory, children, files in os.walk(root, onerror=unreadable.append):
        children[:] = [n for n in children if n not in ('.git', 'node_modules')]
        strays.extend(Path(directory) / n for n in files if ENV_BACKUP.search(n))
    if unreadable:
        listed = ', '.join(str(error.filename) for error in unreadable)
        (warnings if env_backups == 'warn' else fatal).append(
            f'Could not scan for stray environment backups: {listed}. '
            'A directory the deploy user cannot read may hide one. '
            'Make it readable, or move it outside the checkout.')
    if strays:
        # Paths only. These files hold secrets and this message is printed.
        listed = ', '.join(str(p) for p in strays)
        finding = (f'Stray environment backup: {listed}. '
                   'Move it outside the checkout into a private directory. '
                   'Use deploy/backup-env.sh for future snapshots.')
        (warnings if env_backups == 'warn' else fatal).append(finding)
    if fatal:
        raise ValueError('\n'.join(fatal))
    return warnings


def describe_owner(foreign, user, metadata):
    """One repair for the whole tree, plus enough paths to see the shape."""
    shown = ' '.join(shlex.quote(str(p)) for p in foreign[:5])
    more = '' if len(foreign) <= 5 else f' (and {len(foreign) - 5} more)'
    return (f'Git metadata has the wrong owner: {len(foreign)} path(s) under {metadata}{more}. '
            f'Administrator repair for these entries: sudo chown -h '
            f'{shlex.quote(user)} -- {shown}. '
            f'Repair the whole tree in one step: sudo chown -R {shlex.quote(user)} -- '
            f'{shlex.quote(str(metadata))}. Never fetch as root.')


def fail_walk(error):
    """Git metadata is different: what cannot be read cannot be verified, and
    the fetch both scripts perform would fail on it anyway."""
    raise ValueError(f'Cannot read Git metadata at {error.filename}: {error.strerror}. '
                     'The component fetch needs this tree; repair its permissions '
                     'as the checkout owner and never fetch as root.')


def snapshot(root, source, destination):
    root = Path(root).resolve()
    destination = Path(destination).expanduser().resolve()
    if destination == root or root in destination.parents:
        raise ValueError('Environment backup directory must be outside the checkout')
    # A directory owned by someone else must never receive these secrets.
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.stat().st_uid != os.geteuid():
        raise ValueError('Environment backup directory must belong to the invoking user')
    destination.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix=Path(source).name + '.', dir=destination)
    try:
        with os.fdopen(fd, 'wb') as output, open(source, 'rb') as original:
            shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        os.unlink(name)
        raise
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'snapshot'))
    parser.add_argument('root')
    parser.add_argument('--env-file')
    parser.add_argument('--directory', default=str(Path.home() / '.local/state/vidra/env-history'))
    parser.add_argument('--env-backups', choices=('fatal', 'warn'), default='fatal',
                        help="'warn' keeps a hygiene lint from blocking a rollback")
    args = parser.parse_args()
    try:
        if args.command == 'check':
            for warning in check(args.root, env_backups=args.env_backups):
                print(f'[checkout-hygiene] WARNING: {warning}', file=sys.stderr)
        else:
            if not args.env_file:
                parser.error('snapshot requires --env-file')
            print(snapshot(args.root, args.env_file, args.directory))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'[checkout-hygiene] ERROR: {error}\n')


if __name__ == '__main__':
    main()
