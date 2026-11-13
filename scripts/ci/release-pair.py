#!/usr/bin/env python3
"""Name the two releases a qualification drill compares, from releases/v*.json alone."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
# The validator comes from the TOOL checkout; the records it reads may come from
# another commit, so a record commit can never loosen its own validation.
_spec = importlib.util.spec_from_file_location('release_mapping', ROOT / 'deploy/release-mapping.py')
mapping = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mapping)

UNUSABLE = 'release records unusable'
NOT_RECORDED = 'release is not a recorded release'
PREVIOUS_NOT_RECORDED = 'previous release is not a recorded release'
NOT_OLDER = 'previous release is not older than the release'
NO_PREVIOUS = 'release has no previous record'
NOT_ONE_ADDED = 'change does not add exactly one release record'
REASONS = (UNUSABLE, NOT_RECORDED, PREVIOUS_NOT_RECORDED, NOT_OLDER, NO_PREVIOUS, NOT_ONE_ADDED)
# What the workflow's `releases/v*.json` path filter matches, so nothing that
# triggered the run is left uncounted.
ADDED = re.compile(r'releases/(v[^/]*)\.json')


class Refused(ValueError):
    """str() is one of REASONS, never a tag, a path or a record's content."""


def tag(value):
    return type(value) is str and mapping.STRICT_RELEASE_TAG.fullmatch(value) is not None


def records(root):
    found, problems = mapping.load_records(Path(root) / 'releases')
    if problems:
        raise Refused(UNUSABLE)
    return {record['release']: record for record in found}


def _previous(by_tag, release):
    older = [name for name in by_tag if mapping.semver(name) < mapping.semver(release)]
    if not older:
        raise Refused(NO_PREVIOUS)
    return max(older, key=mapping.semver)


def previous(root, release):
    if not tag(release):
        raise Refused(NOT_RECORDED)
    return _previous(records(root), release)


def resolve(root, release, previous=''):
    if not tag(release):
        raise Refused(NOT_RECORDED)
    by_tag = records(root)
    if release not in by_tag:
        raise Refused(NOT_RECORDED)
    if previous:
        if not tag(previous) or previous not in by_tag:
            raise Refused(PREVIOUS_NOT_RECORDED)
        if not mapping.semver(previous) < mapping.semver(release):
            raise Refused(NOT_OLDER)
    else:
        previous = _previous(by_tag, release)
    for name in (previous, release):
        if mapping.record_pairing(Path(root) / 'releases' / f'{name}.json', name)[1]:
            raise Refused(UNUSABLE)
    return {'old': by_tag[previous], 'new': by_tag[release]}


def added(root, names):
    found = [match[1] for match in map(ADDED.fullmatch, names) if match]
    if len(found) != 1:
        raise Refused(NOT_ONE_ADDED)
    if not tag(found[0]) or found[0] not in records(root):
        raise Refused(NOT_RECORDED)
    return found[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('pair', 'added'))
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--release', default='')
    parser.add_argument('--previous', default='')
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'added':
            # NUL-separated, as `git diff -z --name-only --diff-filter=A` writes them.
            names = sys.stdin.buffer.read().decode('utf-8', 'replace').split('\0')
            result = {'release': added(args.root, names)}
        else:
            pair = resolve(args.root, args.release, args.previous)
            result = {'previous': pair['old']['release'], 'release': pair['new']['release']}
            for field in ('core_schema', 'search_schema'):
                result[field] = [pair[side][field + '_version'] for side in ('old', 'new')]
    except Refused as refusal:
        print(f'::error::release pair refused: {refusal}', file=sys.stderr)
        return 1
    if args.github_output:
        with args.github_output.open('a') as out:
            for field in ('previous', 'release'):
                if field in result:
                    out.write(f'{field}={result[field]}\n')
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
