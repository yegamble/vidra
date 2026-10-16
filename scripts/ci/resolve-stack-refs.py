#!/usr/bin/env python3
"""Select floating main or the newest recorded release for stack CI.

Uses the deployment resolver's validated pairing and refuses its uniform-tag
fallback. Release source refs are immutable commits, not movable tag names.
This does not publish, pull, or certify the recorded image digests.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('release_mapping', ROOT / 'deploy/release-mapping.py')
mapping = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mapping)
ROLES = ('core', 'user', 'search')


def select(mode, releases):
    if mode == 'main':
        return {'mode': mode, 'release': '', 'components': {
            role: {'ref': 'main', 'tag': ''} for role in ROLES}}
    records, problems = mapping.load_records(releases)
    if problems:
        raise ValueError('; '.join(problems))
    record = max(records, key=lambda item: mapping.semver(item['release']))
    record_path = releases / (record['release'] + '.json')
    result = subprocess.run([sys.executable, str(ROOT / 'deploy/release-mapping.py'),
                             'resolve', '--release', record['release'], '--record', str(record_path)],
                            capture_output=True, text=True, check=False)
    if result.returncode != mapping.OK:
        raise ValueError(f'release resolver returned {result.returncode}; fallback is forbidden in CI: '
                         + result.stderr.strip())
    expected = [f"{role} {record['components'][role]['tag']} record-tree" for role in ROLES]
    if result.stdout.splitlines() != expected:
        raise ValueError('release resolver did not return the recorded three-component pairing')
    return {'mode': mode, 'release': record['release'],
            'core_schema_version': record['core_schema_version'],
            'search_schema_version': record['search_schema_version'],
            'components': {role: {'ref': record['components'][role]['commit'],
                                  'tag': record['components'][role]['tag']} for role in ROLES}}


def verify(selection, root):
    if selection['mode'] not in ('main', 'release') or set(selection['components']) != set(ROLES):
        raise ValueError('source evidence must name a mode and all three components')
    for role, component in selection['components'].items():
        repo = root / ('vidra-' + role)
        actual = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], check=True,
                                capture_output=True, text=True).stdout.strip()
        if selection['mode'] == 'release' and actual != component['ref']:
            raise ValueError(f'{role}: checkout {actual} differs from recorded commit {component["ref"]}')
        component['checked_out_commit'] = actual
        if selection['mode'] == 'release' and role in ('core', 'search'):
            newest = max(int(p.name.split('_', 1)[0]) for p in (repo / 'migrations').glob('*.up.sql'))
            if newest != selection[role + '_schema_version']:
                raise ValueError(f'{role}: migration ceiling {newest} differs from release record '
                                 f'{selection[role + "_schema_version"]}')
    return selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('select', 'verify'))
    parser.add_argument('--mode', choices=('main', 'release'), default='release')
    parser.add_argument('--releases', type=Path, default=ROOT / 'releases')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'select':
            selected = select(args.mode, args.releases)
            if args.github_output:
                with args.github_output.open('a') as out:
                    for role in ROLES:
                        out.write(f'{role}_ref={selected["components"][role]["ref"]}\n')
                    out.write(f'release={selected["release"]}\n')
        else:
            selected = verify(json.loads(args.evidence.read_text()), args.root)
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(selected, indent=2) + '\n')
        print(json.dumps(selected, indent=2))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'::error::stack ref verification failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
