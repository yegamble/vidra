#!/usr/bin/env python3
"""Refuse a component mapping nobody released, before a deploy or rollback
changes anything.

  python3 deploy/release-mapping.py check --mode deploy --env env/production.env

WHY. The image tags in the env file are three independent strings. Before this
check, nothing asked whether they belonged together. A vidra-user tag from
another release, or a core/search pairing never released together, went
through the pre-deploy dump, the pull, the migrations and `up -d`. The result
is a stack whose frontend calls endpoints this core may lack, or whose search
schema this core's outbox does not feed, and no probe notices. releases/<tag>.json
is the machine-readable statement of what WAS released together; this script
holds the pinned triple against it.

Exit codes are the contract deploy/lib.sh's release_mapping_check reads:
  0  verified: exactly one record pairs these tags (plus digest/bundle checks)
  3  UNVERIFIED but allowed: a pre-manifest release, the tree's own release
     whose record cannot exist yet, or (rollback only) any release-shaped
     triple no record pairs, or a releases/ directory that could not be
     used. Printed as WARNINGs naming what was not verified; the caller
     continues.
  1  refused: a finding that predicts a broken or unreleased deployment. In
     BOTH modes: a tag that is unset or cannot be parsed, a digest that
     contradicts a record that loaded. In a deploy also: release metadata
     that cannot be trusted, a stale bundle, a triple no record pairs.
  2  usage error (argparse)

THE NEWEST RELEASE, AND WHAT STILL DOES NOT VERIFY IT. deploy/release.sh tags
this repository before any image exists, so a tree at vN (or the vN bundle)
cannot carry releases/vN.json, and this script ALONE then only checks that all
three tags say vN. deploy/lib.sh closes that for a host with egress: it fetches
the record from the repository and re-runs this script with --extra-record, so
the pairing and any digest pin are held against the real record after all. Two
cases remain, and neither is reachable by any check: an airgapped host
(VIDRA_RECORD_FETCH=off, no route, no curl), and the window between a release
publishing and its record PR merging, when the record exists nowhere yet. The
second closes when the record ships inside the release artifact.

Stdlib only and NO NETWORK — the fetch lives in deploy/lib.sh, which hands the
result here as a file; this script only ever reads paths it is given. It reads
nothing from the env file except the three VIDRA_*_TAG keys and the two
image-source keys (VIDRA_IMAGE_REGISTRY, VIDRA_IMAGE_OWNER): that file holds
every production secret, and this output is printed to a terminal and to logs.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

OK, REFUSED, UNVERIFIED = 0, 1, 3

COMPONENTS = (('core', 'VIDRA_CORE_TAG', 'vidra-core'),
              ('user', 'VIDRA_USER_TAG', 'vidra-user'),
              ('search', 'VIDRA_SEARCH_TAG', 'vidra-search'))

# The shape deploy/release.sh cuts, and the only one a record may name.
RELEASE_TAG = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+')
COMMIT = re.compile(r'[0-9a-f]{40}')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
PLATFORM = re.compile(r'[a-z0-9]+/[a-z0-9]+(/[a-z0-9]+)?')
REPOSITORY = re.compile(r'[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+')
# What an env file may pin: a Docker tag, optionally with the digest Docker
# would then pull instead (`repo:tag@sha256:...`).
PINNED = re.compile(r'(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})(@(?P<digest>sha256:[0-9a-f]{64}))?')
SEMVER = re.compile(r'v([0-9]+)\.([0-9]+)\.([0-9]+)([-+].*)?')

# WHY NOT COMPARED: `meta_commit` is provenance, never held against the tree
# this runs from. A v0.6.5 tree legitimately deploys or rolls back to v0.6.4
# (rollback.sh runs under the newer bundle on purpose), and a `main` checkout
# is never at any record's commit. The bundle manifest's own meta_commit is
# not compared for the same reason. `evidence` names a path under docs/ that
# bundles do not ship: provenance to look up, not a file to open.
RECORD_KEYS = {'schema_version', 'release', 'meta_commit', 'core_schema_version',
               'search_schema_version', 'components'}
OPTIONAL_RECORD_KEYS = {'evidence'}


def semver(tag):
    """(major, minor, patch) of a vX.Y.Z tag, ignoring a prerelease/build
    suffix exactly as deploy.sh's semver_ge does (v0.6.3-a37 is v0.6.3 code);
    None when the tag is not release-shaped at all."""
    match = SEMVER.fullmatch(tag)
    return tuple(int(part) for part in match.groups()[:3]) if match else None


def schema_int(value):
    # bool is an int in Python; `"core_schema_version": true` is not a ledger.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate(path, data):
    """Every problem with one record, as strings. Unknown keys are refused so a
    typo such as `index_digets` cannot quietly remove a check."""
    where = f'{path.parent.name}/{path.name}'
    problems = []

    def bad(message):
        problems.append(f'{where}: {message}')

    def keys(obj, required, optional, label):
        if not isinstance(obj, dict):
            bad(f'{label} must be an object')
            return False
        missing = sorted(required - obj.keys())
        unknown = sorted(obj.keys() - required - optional)
        if missing:
            bad(f'{label} is missing {", ".join(missing)}')
        if unknown:
            bad(f'{label} has unknown key(s) {", ".join(unknown)}')
        return not missing

    if not keys(data, RECORD_KEYS, OPTIONAL_RECORD_KEYS, 'the record'):
        return problems
    if data['schema_version'] != 1 or isinstance(data['schema_version'], bool):
        bad(f'schema_version is {data["schema_version"]!r}; this checker reads version 1 only')
    release = data['release']
    if not isinstance(release, str) or not RELEASE_TAG.fullmatch(release):
        bad(f'release {release!r} is not a vMAJOR.MINOR.PATCH tag')
    elif path.name != f'{release}.json':
        bad(f'names release {release}, so it must be called {release}.json')
    if not isinstance(data['meta_commit'], str) or not COMMIT.fullmatch(data['meta_commit']):
        bad(f'meta_commit {data["meta_commit"]!r} is not a 40-hex commit')
    for key in ('core_schema_version', 'search_schema_version'):
        if not schema_int(data[key]):
            bad(f'{key} {data[key]!r} is not a positive integer migration version')
    if 'evidence' in data and not isinstance(data['evidence'], str):
        bad('evidence must be a string path')
    components = data['components']
    if not keys(components, {name for name, _, _ in COMPONENTS}, set(), 'components'):
        return problems
    for name, _, repo in COMPONENTS:
        component = components[name]
        label = f'components.{name}'
        if not keys(component, {'tag', 'commit', 'image'}, set(), label):
            continue
        if not isinstance(component['tag'], str) or not RELEASE_TAG.fullmatch(component['tag']):
            bad(f'{label}.tag {component["tag"]!r} is not a vMAJOR.MINOR.PATCH tag')
        if not isinstance(component['commit'], str) or not COMMIT.fullmatch(component['commit']):
            bad(f'{label}.commit {component["commit"]!r} is not a 40-hex commit')
        image = component['image']
        if not keys(image, {'repository', 'index_digest', 'platforms'}, set(), f'{label}.image'):
            continue
        if not isinstance(image['repository'], str) or not REPOSITORY.fullmatch(image['repository']) \
                or not image['repository'].endswith('/' + repo):
            bad(f'{label}.image.repository {image["repository"]!r} is not a registry path ending in /{repo}')
        if not isinstance(image['index_digest'], str) or not DIGEST.fullmatch(image['index_digest']):
            bad(f'{label}.image.index_digest {image["index_digest"]!r} is not a sha256 digest')
        platforms = image['platforms']
        if not isinstance(platforms, dict) or not platforms:
            bad(f'{label}.image.platforms must name at least one platform digest')
            continue
        for platform, value in platforms.items():
            if not PLATFORM.fullmatch(platform):
                bad(f'{label}.image.platforms key {platform!r} is not an os/arch platform')
            if not isinstance(value, str) or not DIGEST.fullmatch(value):
                bad(f'{label}.image.platforms[{platform}] {value!r} is not a sha256 digest')
    return problems


def load_extra_record(path, records, env):
    """One record from OUTSIDE releases/, for this run only: (record, why-not).

    deploy/lib.sh fetches releases/<tag>.json from the repository when this
    tree cannot carry it yet, and passes it here as --extra-record. The whole
    point is that it may only ever ADD verification, so every rejection below
    returns a WARNING string and leaves the caller's verdict exactly where it
    was.

    ADMITTED only when it pairs EXACTLY the triple this run pins, and only
    when releases/ does not already speak for that release. A record for some
    other release must not join the set: `newest`, the recorded-release list
    and the per-component findings are all computed over it, so widening it
    silently changes verdicts about releases nobody fetched anything for. A
    record the tree already carries must not be replaced either — releases/ on
    disk is this tree's own statement, and a file handed in for one run does
    not get to overrule it.
    """
    pinned = tuple(env[name] for name, _, _ in COMPONENTS)
    unusable = (f'the record supplied with --extra-record ({path}) is unusable: %s. Nothing it '
                'might have said was used, and this run is exactly where it would have been '
                'without it. A record that cannot be read predicts nothing about the images '
                'being deployed.')
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        return None, unusable % error
    problems = validate(Path(path), data)
    if problems:
        return None, unusable % '; '.join(problems)
    triple = tuple(data['components'][name]['tag'] for name, _, _ in COMPONENTS)
    described = ' '.join(f'{name}={tag}' for (name, _, _), tag in zip(COMPONENTS, triple))
    if any(record['release'] == data['release'] for record in records):
        return None, (f'--extra-record ({path}) is another copy of release {data["release"]}, which '
                      'this tree already carries a record for. It was IGNORED: the record on disk '
                      'is this tree\'s own statement, and a file supplied for one run does not '
                      'replace it.')
    if triple != pinned:
        return None, (f'--extra-record ({path}) is release {data["release"]}, pairing {described}, '
                      'which is not the triple this run pins ('
                      + ' '.join(f'{name}={env[name]}' for name, _, _ in COMPONENTS)
                      + '). It was IGNORED: a record for another release would join the set every '
                        'verdict here is computed against, and a file fetched for one release must '
                        'not change the answer for a different one. It is not an override.')
    if any(tuple(record['components'][name]['tag'] for name, _, _ in COMPONENTS) == triple
           for record in records):
        return None, (f'--extra-record ({path}) pairs {described}, exactly like a record already in '
                      'this tree. It was IGNORED rather than added: two records pairing one triple '
                      'cannot say which release is being deployed.')
    return data, ''


def load_records(directory):
    """(records, problems). Every file is read and every problem collected, so
    one run names every broken record instead of one per attempt."""
    directory = Path(directory)
    if not directory.is_dir():
        return [], [f'{directory} does not exist, so no pinned tags can be checked against a '
                    'released mapping. It ships with this repository and inside every bundle; '
                    'a tree without it is incomplete. Restore it from the release this tree '
                    'came from.']
    records, problems = [], []
    for path in sorted(directory.glob('*.json')):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            problems.append(f'{directory.name}/{path.name}: unreadable JSON ({error})')
            continue
        found = validate(path, data)
        problems.extend(found)
        if not found:
            records.append(data)
    if not records and not problems:
        problems.append(f'{directory} holds no release records (*.json). Nothing can be verified '
                        'against it; restore the directory from the release this tree came from.')
    seen = {}
    for record in records:
        triple = tuple(record['components'][name]['tag'] for name, _, _ in COMPONENTS)
        if triple in seen:
            problems.append(f'{directory.name}/{record["release"]}.json pairs core={triple[0]} '
                            f'user={triple[1]} search={triple[2]}, exactly like '
                            f'{directory.name}/{seen[triple]}.json. Two releases cannot share one '
                            'mapping: the check could not say which one is being deployed.')
        else:
            seen[triple] = record['release']
    return records, problems


def compose_value(raw):
    """A value as Compose's env-file parser reads it (compose-go dotenv,
    extractVarValue, checked at v2.14.0). Unquoted, it cuts an inline comment at
    ` #` and trims trailing whitespace. Quoted, it takes everything up to the
    closing quote. deploy.sh hands over env_get's raw text, which keeps both, and
    refusing `VIDRA_USER_TAG=v0.6.4 # pinned` would stop a deploy Compose would
    have run happily."""
    value = raw.replace('\r', '').lstrip(' \t')
    if value[:1] in ('"', "'"):
        end = value.find(value[0], 1)
        return value[1:end] if end != -1 else value
    return value.split(' #', 1)[0].rstrip()


def env_file_value(path, key):
    """deploy/lib.sh's env_get, for one key: a non-empty process environment
    variable wins (compose interpolation applies the same precedence), else the
    LAST `KEY=value` line. The raw text is returned; compose_value normalises it.
    Never sources the file and never looks at any other key."""
    value = os.environ.get(key, '')
    if value:
        return value
    if path is None:
        return ''
    pattern = re.compile(r'^[ \t]*' + re.escape(key) + r'[ \t]*=[ \t]*(.*)$')
    found = ''
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            match = pattern.match(line.rstrip('\n'))
            if match:
                found = match.group(1)
    return found


def bundle_manifest(path):
    """key=value lines, read the way deploy/lib.sh's bundle_manifest_get reads
    them (last value wins)."""
    values = {}
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip().replace('\r', '')
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def check(args):
    """(exit code, errors, warnings, notes)."""
    errors, warnings, notes = [], [], []
    records, problems = load_records(args.releases)

    pins = {}
    for name, key, repo in COMPONENTS:
        explicit = getattr(args, name)
        raw = explicit if explicit else env_file_value(args.env, key)
        value = compose_value(raw)
        match = PINNED.fullmatch(value) if value else None
        if not value:
            errors.append(f'{key} is not set{" in " + str(args.env) if args.env else ""}. Without it '
                          f'there is no {repo} image to pull, and the compose render refuses the '
                          'stack later anyway; set it to the tag of a recorded release.')
        elif not match:
            errors.append(f'{key}={raw!r} is {value!r} as Compose reads it, which is not a Docker '
                          'image tag (optionally @sha256:<digest>), so no image can be pulled under it.')
        elif semver(match.group('tag')) is None:
            # `latest`, `main`, `sha-abc123`: a Docker tag, but not one a release
            # is cut as, so no record can name it and nothing can be verified
            # about the image under it. Fatal in every mode, records or no
            # records: deploy.sh's migrator floor refuses the core/search
            # spellings anyway, and a rollback to it is a rollback to nothing
            # releases/ could ever describe.
            errors.append(f'{key}={raw!r} is {match.group("tag")!r}, which is not a release tag '
                          '(vMAJOR.MINOR.PATCH, optionally with a suffix). Releases are cut as semver '
                          'tags, so no record can name it and nothing about the image under it can be '
                          'verified. Nothing was changed.')
        else:
            pins[name] = (key, repo, match.group('tag'), match.group('digest'))

    tree_tags = set(args.tree_tag or [])
    bundle = None
    if args.bundle_manifest:
        try:
            bundle = bundle_manifest(args.bundle_manifest)
        except OSError as error:
            problems.append(f'{args.bundle_manifest} cannot be read ({error.strerror}), so this '
                            'bundle tree cannot be identified. Re-download the bundle.')
        else:
            if bundle.get('tag'):
                tree_tags.add(bundle['tag'])

    # A tag that is unset or cannot be parsed stops EVERY mode: deploy.sh's
    # checkout sync would `git checkout` it and rollback.sh's env_set_key would
    # write it. Every finding is reported with it, so one run names everything.
    if len(pins) != len(COMPONENTS):
        return REFUSED, errors + problems, warnings, notes

    # Release metadata that cannot be trusted: a missing releases/, a corrupt or
    # malformed record, two records pairing one triple, an unreadable manifest.
    # A DEPLOY stops here. Matching against a half-valid record set would turn a
    # typo in one file into a misleading verdict about another, and a deploy is
    # the moment to fix the tree. A ROLLBACK does not (H1): a corrupt record for
    # some OTHER release, or a releases/ directory that is simply not there,
    # predicts nothing about whether the TARGET's images work, and a finding
    # may only stop what it predicts. It is a WARNING that names what was
    # therefore not verified. The records that DID load are still used, so a
    # digest that contradicts one of them stays fatal below.
    if problems and args.mode == 'deploy':
        return REFUSED, problems, warnings, notes
    warnings.extend(problems)

    releases = Path(args.releases).name
    env = {name: pins[name][2] for name, _, _ in COMPONENTS}
    described = ' '.join(f'{name}={env[name]}' for name, _, _ in COMPONENTS)
    # Read like the tags: the explicit value lib.sh resolved with env_get, else
    # the env file. `${VAR:-default}` in the compose file takes the default when
    # the key is unset OR empty, so an empty value is the default here too.
    registry = compose_value(args.registry or env_file_value(args.env, 'VIDRA_IMAGE_REGISTRY')) or 'ghcr.io'
    owner = compose_value(args.owner or env_file_value(args.env, 'VIDRA_IMAGE_OWNER')) or 'yegamble'
    source = f'{registry}/{owner}'

    # THE FETCHED RECORD (--extra-record). Absent, nothing below changes at
    # all. Present and admitted, it joins `records` for this run only, and
    # because it pairs the pinned triple exactly it can only ever reach the
    # `matches` branch below: the pairing is verified, any digest pin is held
    # against it, and a contradiction is as fatal as it is for a tree record.
    # Rejected, it is a WARNING and the run keeps the verdict it already had.
    extra = None
    if args.extra_record:
        extra, why = load_extra_record(args.extra_record, records, env)
        if extra is None:
            warnings.append(why)
        else:
            records = records + [extra]
            notes.append(f'{releases}/{extra["release"]}.json is not in this tree (release.sh tags '
                         'this repository before any image exists, so a tree at a release cannot '
                         f'carry its own record); the copy at {args.extra_record} was supplied with '
                         '--extra-record and is used for THIS RUN ONLY. Nothing was written to '
                         f'{releases}/.')

    def where_of(record):
        """Provenance, per record: a fetched record must never be reported as
        if this tree had vouched for it."""
        if extra is not None and record['release'] == extra['release']:
            return f'{args.extra_record} (fetched for this run, not {releases}/)'
        return f'{releases}/{record["release"]}.json'

    matches = [r for r in records if all(r['components'][n]['tag'] == env[n] for n, _, _ in COMPONENTS)]

    if not records:
        # Rollback only: load_records reports a missing or empty directory as a
        # problem, and a deploy returned on it above.
        warnings.append(f'{releases}/ could not be used (above), so NOTHING about {described} was '
                        'verified: not the pairing, not the digests.' + pinned_note(pins)
                        + ' The rollback continues because a record set that cannot be read predicts '
                        'nothing about whether these images work. Fix the records after service is back.')
        return UNVERIFIED, errors, warnings, notes

    if matches:
        where = ', '.join(where_of(r) for r in matches)
        # THE IMAGE SOURCE (M5). docker-compose.prod.yml pulls
        # ${VIDRA_IMAGE_REGISTRY:-ghcr.io}/${VIDRA_IMAGE_OWNER:-yegamble}/<repo>:<tag>.
        # A record describes the images at ITS repository; a fork's or a
        # mirror's images under the same tag are different bytes the record
        # cannot vouch for. That is legitimate (deploying a fork is exactly what
        # those two keys are for), so it is UNVERIFIED with a warning naming both
        # repositories, and the digest comparison below is skipped: a fork's
        # image cannot carry the upstream digest, and refusing it would be a
        # verdict about images the record has never seen.
        foreign = []
        for name, key, repo in COMPONENTS:
            effective = f'{source}/{repo}'
            recorded = sorted({r['components'][name]['image']['repository'] for r in matches})
            if effective not in recorded:
                foreign.append(f'{effective} instead of {" or ".join(recorded)}')
        if foreign:
            warnings.append(f'this env pulls {"; ".join(foreign)} (VIDRA_IMAGE_REGISTRY={registry}, '
                            f'VIDRA_IMAGE_OWNER={owner}), but {where} describes the images at the '
                            f'recorded repository. A fork or a mirror is legitimate, and the record '
                            f'cannot speak for its images: NOT verified that {described} under '
                            f'{source} is the release\'s bytes, and digest pins were not compared.'
                            + pinned_note(pins) + ' Continuing.')
        # More than one match means two records pair this triple, which is one
        # of the problems above (fatal in a deploy, warned in a rollback). A
        # digest pin is then held against BOTH: it contradicts the release only
        # when neither record shipped it.
        for name, key, repo in COMPONENTS:
            pinned = pins[name][3]
            if not pinned or foreign:
                continue
            allowed, recorded = [], []
            for record in matches:
                image = record['components'][name]['image']
                allowed += [image['index_digest'], *image['platforms'].values()]
                recorded.append(f'{where_of(record)} records {repo} {env[name]} as '
                                f'index {image["index_digest"]} '
                                f'({", ".join(f"{p} {d}" for p, d in image["platforms"].items())})')
            if pinned not in allowed:
                errors.append(f'{key} pins digest {pinned}, but {"; ".join(recorded)}. '
                              'Docker pulls by digest, so this would run bytes that release never '
                              'shipped under a tag that claims it did. Nothing was changed.')
        record = matches[0]
        if bundle is not None and args.mode == 'deploy':
            errors.extend(bundle_findings(bundle, record, where, args.bundle_manifest))
        elif bundle is not None:
            notes.append('rollback: vidra-bundle.manifest not compared. A bundle host rolls back by '
                         're-pointing tags under the newer bundle, and rollback.sh never reads the '
                         "manifest's schema version, so a difference predicts nothing here.")
        if errors:
            return REFUSED, errors, warnings, notes
        if problems:
            # Rollback only (a deploy returned on problems above).
            warnings.append(f'{described} is paired by {where}, and its digest pins were held against '
                            f'that record, but {releases}/ has the problems above, so the record set '
                            'as a whole cannot be trusted. Fix the records after service is back.')
            return UNVERIFIED, errors, warnings, notes
        if foreign:
            return UNVERIFIED, errors, warnings, notes
        notes.append(f'{described} is release {record["release"]} ({where}): core schema '
                     f'{record["core_schema_version"]}, search schema {record["search_schema_version"]}')
        return OK, errors, warnings, notes

    owners = {name: sorted(r['release'] for r in records if r['components'][name]['tag'] == env[name])
              for name, _, _ in COMPONENTS}
    known = ', '.join(sorted((r['release'] for r in records), key=semver)) or '(none)'
    floor = min((r['release'] for r in records), key=semver)
    uniform = len(set(env.values())) == 1
    tag = env['core']

    # A STALE BUNDLE, whatever the records say. The record-based comparison above
    # needs a matching record; without one, the v0.6.5 bundle unpacked over an
    # install still pinning v0.6.3 used to warn here and then dump, pull and
    # migrate before deploy.sh's ledger assertion compared v0.6.3's migrator with
    # v0.6.5's schema number. The bundle is built from the core tag, so the two
    # must agree. Rollbacks run under a newer bundle on purpose; not checked there.
    if bundle is not None and args.mode == 'deploy' and bundle.get('tag', '') != tag:
        errors.append(f'{args.bundle_manifest}: vidra-bundle.manifest tag is {bundle.get("tag") or "(missing)"} '
                      f'but VIDRA_CORE_TAG={tag}. deploy.sh takes the expected core schema version from '
                      'this manifest, so the migrator would be checked against another release\'s '
                      'number after the dump, pull and migrations have already run, and this tree\'s '
                      'compose files belong to that other release. Nothing was changed. Unpack the '
                      f'{tag} bundle over this tree, or pin the release this bundle is.')

    if not any(owners.values()) and all(semver(env[n]) < semver(floor) for n, _, _ in COMPONENTS):
        warnings.append(f'{described} is a release from before {floor}, the first one with a record '
                        f'in {releases}/. Its component mapping and digests are NOT verified. '
                        + ('That alone would not stop this run: refusing would make every historical '
                           'release undeployable and un-rollback-able.' if errors else
                           'Continuing, because refusing would make every historical release '
                           'undeployable and un-rollback-able.') + pinned_note(pins))
        return (REFUSED if errors else UNVERIFIED), errors, warnings, notes

    # A UNIFORM triple newer than every record: the tree's own release (tag vN
    # or the vN bundle), or vN deployed from main by a fresh `install.sh --git`
    # or a rehearsal lab. Neither can carry releases/vN.json yet: release.sh
    # tags this repository before any image exists, and the record lands on
    # main after the images are verified. `git tag --points-at HEAD` is empty
    # on main one commit after the tag, so the tree's tags alone would refuse
    # the first deploy of every release until the owner hand-lands the record.
    # A typo'd uniform tag is still caught by the checkout sync and `compose
    # pull`; the mixed-triple refusal below is where the value is.
    newest = max((r['release'] for r in records), key=semver)
    if not any(owners.values()) and uniform and (tag in tree_tags or semver(tag) > semver(newest)):
        warnings.append(f'{described} is newer than every record in {releases}/ (newest: {newest}), '
                        f'and {releases}/{tag}.json is not in this tree. '
                        + (f'It is this tree\'s own release: deploy/release.sh tags this repository '
                           f'before any image exists, so a tree at {tag} cannot carry {tag}\'s record. '
                           if tag in tree_tags else
                           'A tree on main (a fresh install.sh --git, or a rehearsal lab deploying a '
                           'prerelease) gets the record only after the images are verified and it '
                           'lands. ')
                        + 'NOT verified: that these three images were released together, and their '
                        'digests. Only the tag strings were compared; a tag that does not exist still '
                        'fails the checkout sync or the pull. deploy/lib.sh asks again with the record '
                        'fetched from the repository, so this verdict is the one that STANDS only '
                        'where that cannot happen: an airgapped host, or the window before the '
                        "record's PR merges, when it exists nowhere yet." + pinned_note(pins))
        return (REFUSED if errors else UNVERIFIED), errors, warnings, notes

    findings = []
    for name, key, repo in COMPONENTS:
        version = semver(env[name])
        if owners[name]:
            findings.append(f'{key}={env[name]} belongs to release {", ".join(owners[name])}')
        elif version < semver(floor):
            findings.append(f'{key}={env[name]}: no release record names this {repo} tag (it '
                            f'predates {floor}, the first recorded release)')
        else:
            findings.append(f'{key}={env[name]}: no release record names this {repo} tag '
                            f'(recorded releases: {known})')
    if any(owners.values()):
        best = max(sum(r['components'][n]['tag'] == env[n] for n, _, _ in COMPONENTS) for r in records)
        for record in sorted(records, key=lambda r: semver(r['release'])):
            if sum(record['components'][n]['tag'] == env[n] for n, _, _ in COMPONENTS) != best:
                continue
            for name, key, _ in COMPONENTS:
                expected = record['components'][name]['tag']
                if expected != env[name]:
                    findings.append(f'release {record["release"]} expects {key}={expected} '
                                    f'(env has {env[name]})')

    if args.mode == 'rollback':
        # THE DOCUMENTED ROLLBACK. rollback.sh's own usage rolls back ONE component
        # (`--user v0.2.0` under the core and search being served), which is a
        # triple no record pairs by construction. Mid-incident, refusing it
        # predicts no failure of the rollback: a tag that does not exist still
        # fails the pull, which puts the env file back. So it continues, and says
        # precisely what nobody checked. A digest that contradicts a record and
        # a tag that is not release-shaped stay fatal above.
        warnings.extend(findings)
        warnings.append(f'{described} is not a recorded release: these images were never released '
                        'together as far as releases/ knows. NOT verified: that this frontend, core '
                        'API and search schema work as a set, that these tags exist (the pull below '
                        'still fails on one that does not), and their digests.' + pinned_note(pins)
                        + ' The rollback continues because a missing pairing record does not predict '
                        'that it fails. Once service is back, return to a recorded release '
                        f'({known}) or record this pairing.')
        return UNVERIFIED, errors, warnings, notes

    # THE OVERRIDE (VIDRA_RELEASE_MAPPING=warn, passed by lib.sh as --unrecorded
    # warn). It covers exactly this refusal, the pairing, and nothing above it:
    # an unparseable tag, a broken record set and a digest contradiction
    # returned before this point, and a stale bundle is in `errors` here, so the
    # override cannot reach past any of them.
    if args.unrecorded == 'warn' and not errors:
        warnings.extend(findings)
        warnings.append(f'VIDRA_RELEASE_MAPPING=warn: {described} is not a recorded release and would '
                        'have stopped this deploy. NOT verified: that these images were released '
                        'together (a UI calling endpoints this core lacks, a search index this '
                        "core's outbox does not feed), that these tags exist (the checkout sync or "
                        'the pull still fails on one that does not), and their digests.'
                        + pinned_note(pins) + ' Continuing on the override. Unset it once '
                        f'{releases}/ records this pairing (recorded releases: {known}).')
        return UNVERIFIED, errors, warnings, notes

    errors.extend(findings)
    if any(owners.values()):
        errors.append(f'{described} is not a recorded release: these images were never released '
                      'together, so nothing verified that this frontend, core API and search '
                      'schema work as a set (a UI calling endpoints this core lacks, a search '
                      "index this core's outbox does not feed). Nothing was changed. Pin one "
                      f'recorded release ({known}), or, if this pairing really was released, add '
                      f'its record under {releases}/ on main and update this tree, or deploy it '
                      'anyway with VIDRA_RELEASE_MAPPING=warn.')
    else:
        hint = (f'add {releases}/{tag}.json on main and update this tree to a commit that carries '
                'it, or pin the tree itself to that release with deploy/pin-release.sh'
                if uniform else 'pin one recorded release, or record this pairing')
        errors.append(f'{described} is not a recorded release, so nothing says these images exist or '
                      'were released together. Deploying it runs a mapping nobody verified, against '
                      'this tree\'s compose files and migration expectations, which may belong to a '
                      f'different release. Nothing was changed. Either {hint}, or deploy it anyway '
                      'with VIDRA_RELEASE_MAPPING=warn.')
    return REFUSED, errors, warnings, notes


def pinned_note(pins):
    pinned = [f'{key}@{digest}' for key, _, _, digest in pins.values() if digest]
    return f' Digest pins not checked: {", ".join(pinned)}.' if pinned else ''


def bundle_findings(bundle, record, where, path):
    """deploy.sh trusts vidra-bundle.manifest's core_schema_version as the
    independent opinion its ledger assertion compares the migrator against.
    A manifest from another release makes that assertion fail AFTER the dump,
    the pull and the migrations have run, or pass against the wrong number.

    The bundle is a vidra-core release asset built with `--tag <core tag>`, so
    its tag is compared with the record's CORE tag, not the platform tag: a
    platform release that re-releases only vidra-user ships no new bundle."""
    core = record['components']['core']
    findings = []
    tag = bundle.get('tag', '')
    # A record OLDER than the bundle may be a host mid-rollback: rollback.sh
    # re-points the tags under the newer bundle on purpose (and never reads its
    # schema version), so that is the other way forward. A bundle older than
    # the record is a stale tree, and gets only the first.
    older = semver(tag) is not None and semver(core['tag']) < semver(tag)
    consequence = ("deploy.sh would compare the migrator's ledger against this bundle's number, "
                   'failing after the dump, pull and migrations have already run, or passing '
                   'against the wrong release. Nothing was changed. Unpack the '
                   f'{core["tag"]} bundle over this tree'
                   + (f', or roll back with `deploy/rollback.sh {core["tag"]}`, which runs under '
                      'the newer bundle on purpose.' if older else '.'))
    if tag != core['tag']:
        findings.append(f'{path}: vidra-bundle.manifest tag is {tag or "(missing)"}, expected '
                        f'{core["tag"]} (the core tag of release {record["release"]}, {where}). '
                        'This tree\'s compose files and scripts belong to another release. '
                        + consequence)
    schema = bundle.get('core_schema_version', '')
    if not schema.isdigit() or int(schema) != record['core_schema_version']:
        findings.append(f'{path}: vidra-bundle.manifest core_schema_version is {schema or "(missing)"}, '
                        f'expected {record["core_schema_version"]} ({where}). ' + consequence)
    commit = bundle.get('core_commit', '')
    if COMMIT.fullmatch(commit) and commit != core['commit']:
        findings.append(f'{path}: vidra-bundle.manifest core_commit is {commit}, expected '
                        f'{core["commit"]} ({where}). ' + consequence)
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('check',))
    parser.add_argument('--mode', choices=('deploy', 'rollback'), required=True,
                        help='rollback skips the bundle comparison and warns (instead of refusing) '
                             'on a triple no record pairs and on a releases/ that cannot be used; '
                             'an unparseable tag and a digest contradicting a loaded record stay fatal')
    parser.add_argument('--releases', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'releases')
    parser.add_argument('--env', type=Path, help='env file to read VIDRA_*_TAG from')
    parser.add_argument('--core', help='effective VIDRA_CORE_TAG (overrides --env)')
    parser.add_argument('--user', help='effective VIDRA_USER_TAG (overrides --env)')
    parser.add_argument('--search', help='effective VIDRA_SEARCH_TAG (overrides --env)')
    parser.add_argument('--registry', help='effective VIDRA_IMAGE_REGISTRY (overrides --env; '
                                           'empty or absent = ghcr.io, as the compose file defaults it)')
    parser.add_argument('--owner', help='effective VIDRA_IMAGE_OWNER (overrides --env; '
                                        'empty or absent = yegamble, as the compose file defaults it)')
    parser.add_argument('--bundle-manifest', type=Path,
                        help="this tree's vidra-bundle.manifest, when it is an unpacked bundle")
    parser.add_argument('--extra-record', type=Path,
                        help='ONE release record from outside --releases, used for this run only '
                             '(deploy/lib.sh fetches the record this tree cannot carry yet). It is '
                             'validated exactly like a record in the tree and admitted only when it '
                             'pairs the pinned triple and names a release the tree has no record '
                             'for; otherwise it is IGNORED with a warning. Never a refusal on its '
                             'own: a record that could not be read predicts nothing')
    parser.add_argument('--tree-tag', action='append',
                        help='a tag pointing at this checkout\'s HEAD (repeatable)')
    parser.add_argument('--unrecorded', choices=('refuse', 'warn'), default='refuse',
                        help='what deploy/lib.sh passes for VIDRA_RELEASE_MAPPING=warn: a deploy of '
                             'a triple no record pairs WARNS (exit 3) instead of refusing. Never '
                             'reaches an unparseable tag, a broken releases/, a digest contradiction '
                             'or a stale bundle')
    args = parser.parse_args()
    try:
        code, errors, warnings, notes = check(args)
    except OSError as error:
        code, errors, warnings, notes = REFUSED, [f'cannot read {error.filename}: {error.strerror}'], [], []
    for note in notes:
        print(f'[release-mapping] {note}')
    for warning in warnings:
        print(f'[release-mapping] WARNING: {warning}', file=sys.stderr)
    for error in errors:
        print(f'[release-mapping] ERROR: {error}', file=sys.stderr)
    return code


if __name__ == '__main__':
    sys.exit(main())
