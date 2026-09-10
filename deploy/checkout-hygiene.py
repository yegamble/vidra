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
import tempfile


def check(root):
    root = Path(root).resolve()
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
            for path in paths:
                if path.lstat().st_uid != owner:
                    raise ValueError(f'Git metadata has the wrong owner: {path}. '
                                     f'Administrator repair for this entry: sudo chown -h '
                                     f'{shlex.quote(user)} -- {shlex.quote(str(path))}. '
                                     'Rerun preflight to find any remaining entries; never fetch as root.')
    for directory, children, files in os.walk(root, onerror=fail_walk):
        children[:] = [n for n in children if n not in ('.git', 'node_modules')]
        for name in files:
            if re.search(r'\.env(?:\.(?:bak|old|orig|save)(?:$|[.-])|~$)', name):
                raise ValueError(f'Stray environment backup: {Path(directory) / name}. '
                                 'Move it outside the checkout into a private directory. '
                                 'Use deploy/backup-env.sh for future snapshots.')


def fail_walk(error):
    raise error


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
    args = parser.parse_args()
    try:
        if args.command == 'check':
            check(args.root)
        else:
            if not args.env_file:
                parser.error('snapshot requires --env-file')
            print(snapshot(args.root, args.env_file, args.directory))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'[checkout-hygiene] ERROR: {error}\n')


if __name__ == '__main__':
    main()
