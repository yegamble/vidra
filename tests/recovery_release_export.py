#!/usr/bin/env python3
"""Export reviewed recovery-drill evidence from one acceptance host.

Named result files and screenshots only. Raw command output stays private on
the host and is represented by its SHA-256; container health-probe output is
hashed the same way. Before anything is written the export is scanned for every
real secret this host holds (env-file secrets, the test-bucket key, the owner
password, the TOTP secret and recovery codes) and refused on any match. The
manifest records what the scan actually loaded (`secrets_loaded`), and an
export missing any source it NAMED is refused: "no secret found" must never be
mistaken for "no secret looked for".

The bucket key and the owner fixture live under per-candidate paths, so they are
arguments, not constants. Leaving them at the v0.6.4 defaults on a v0.6.5 host
would have scanned neither file and certified the export anyway; now the export
is refused instead. The replacement host legitimately holds no key FILE, which
`--b2-key none` declares on the record (see required_sources).

  # source host
  python3 recovery_release_export.py DRILL_DIR OUT_DIR STAGE [STAGE...] \\
      --baseline /root/vidra-v065-runtime --b2-key /root/vidra-v065-b2-key.json
  # replacement host
  python3 recovery_release_export.py DRILL_DIR OUT_DIR STAGE [STAGE...] \\
      --baseline /root/vidra-v065-runtime --b2-key none
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

# `_KEY_ID` is included on purpose: a bucket key id is half of a credential
# pair and must not reach the public record either.
SECRET_KEY = re.compile(r'(SECRET|PASSWORD|TOKEN|KEK|_KEY$|_KEY_ID$|ACCESS_KEY)')

# Where an acceptance host keeps the secrets the scan must know about. The env
# file is the deployment's, identical on every candidate; the other two are the
# drilled candidate's and default to v0.6.4 so those records stay reproducible.
ENV_FILE = Path('/opt/vidra/env/production.env')
DEFAULT_BASELINE = Path('/root/vidra-v064-runtime')
DEFAULT_B2_KEY = Path('/root/vidra-v064-b2-key.json')
# Sources the command line names, and therefore asserts it scanned. `mfa` is
# left out: it is written by the drill's mfa-enroll action under DRILL_DIR, so
# an export taken before that action legitimately has none.
REQUIRED_SOURCES = ('env', 'bucket_key', 'owner')
DECLARED_ABSENT = 'declared-absent'


def owner_path(baseline):
    return Path(baseline) / 'private/owner.json'


def resolve_baseline(value):
    return Path(value).resolve()


def bucket_key_argument(value):
    """`--b2-key none` declares that this host holds no standalone key file."""
    return None if value == 'none' else Path(value)


def required_sources(bucket_key_file):
    """Which named sources this export asserts it scanned.

    The B2 key file exists only on the SOURCE host: the replacement host is
    rebuilt blank from the released bundle and never holds one, so requiring it
    there would refuse every replacement-half export (`py-restore`,
    `verify-restore`, …). `--b2-key none` takes it out of the required set and
    writes DECLARED_ABSENT into `secrets_loaded`, so the narrower scan is a
    decision on the record rather than a file that silently was not there.

    The credential itself stays covered: the replacement host's restored
    /opt/vidra/env/production.env carries STORAGE_S3_ACCESS_KEY and
    STORAGE_S3_SECRET_KEY, which the env scan loads. What is declared absent is
    the standalone key FILE, never the secret.
    """
    if bucket_key_file is None:
        return tuple(name for name in REQUIRED_SOURCES if name != 'bucket_key')
    return REQUIRED_SOURCES


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def hash_health_output(value):
    if isinstance(value, dict):
        if 'Output' in value and isinstance(value['Output'], str):
            value['output_sha256'] = sha_bytes(value.pop('Output').encode())
        for child in value.values():
            hash_health_output(child)
    elif isinstance(value, list):
        for child in value:
            hash_health_output(child)
    return value


def host_secrets(drill, env_file=ENV_FILE, bucket_key_file=DEFAULT_B2_KEY,
                 owner_file=owner_path(DEFAULT_BASELINE)):
    """Collect the host's secret values and record what was actually loaded.

    The v0.6.4 drill exports were scanned by a revision that read each source
    only `if path.exists()` and kept no note of it, so a missing file silently
    shrank the scan. `loaded` is written into the export manifest so the record
    says which sources the scan covered; export() refuses a source it required.
    """
    secrets = set()
    loaded = {'env': 0, 'bucket_key': False, 'mfa': False, 'owner': False}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                value = value.strip().strip('"\'')
                if SECRET_KEY.search(key.strip()) and len(value) >= 8:
                    secrets.add(value)
                    loaded['env'] += 1
    def collect(value):
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, str) and len(value) >= 8:
            secrets.add(value)
    for name, path in (('bucket_key', bucket_key_file), ('mfa', drill / 'private/mfa.json')):
        if path is None:
            # Declared absent by the caller (see required_sources), not simply
            # not found: the record must be able to tell those apart.
            loaded[name] = DECLARED_ABSENT
        elif path.exists():
            collect(json.loads(path.read_text()))
            loaded[name] = True
    if owner_file.exists():
        secrets.add(json.loads(owner_file.read_text())['password'])
        loaded['owner'] = True
    return secrets, loaded


def leaks(files, secrets):
    found = []
    for name, data in files.items():
        for secret in secrets:
            if secret.encode() in data:
                found.append(name)
                break
    return sorted(found)


def export(drill, out, stages, required=('env',), **sources):
    files = {}
    for stage in stages:
        directory = drill / stage
        result = hash_health_output(json.loads((directory / 'result.json').read_text()))
        files[f'{stage}/result.json'] = (json.dumps(result, indent=2) + '\n').encode()
        commands = directory / 'private/commands.jsonl'
        if commands.exists():
            rows = []
            for line in commands.read_text().splitlines():
                row = json.loads(line)
                log = directory / 'private' / row['log']
                row['log_sha256'] = sha_bytes(log.read_bytes()) if log.exists() else None
                row['log_visibility'] = 'retained privately on host; output not exported'
                rows.append(row)
            files[f'{stage}/commands.json'] = (json.dumps(rows, indent=2) + '\n').encode()
        for image in sorted(directory.glob('*.png')):
            files[f'{stage}/{image.name}'] = image.read_bytes()
    secrets, loaded = host_secrets(drill, **sources)
    # A source that was named but not read makes the scan narrower than the
    # record claims, and a clean result then proves nothing about it.
    scanned = {'env': sources.get('env_file', ENV_FILE),
               'bucket_key': sources.get('bucket_key_file', DEFAULT_B2_KEY),
               'owner': sources.get('owner_file', owner_path(DEFAULT_BASELINE)),
               'mfa': drill / 'private/mfa.json'}
    missing = [name for name in required if not loaded[name]]
    if missing:
        raise SystemExit('refusing export: no secret was loaded from ' +
                         ', '.join(f'{name} ({scanned[name]})' for name in missing) +
                         ' — missing, or holding no secret value, so a clean scan would prove nothing')
    found = leaks(files, secrets)
    if found:
        raise SystemExit(f'refusing export: host secret material found in {found}')
    out.mkdir(mode=0o700)
    for name, data in files.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {name: sha_bytes(data) for name, data in sorted(files.items())}
    # The v0.6.4 exports (exporter sha256 12b22ba4…) wrote the bare name→hash
    # map; the manifest now nests it under `files` beside the scan set.
    (out / 'artifact-hashes.json').write_text(
        json.dumps({'files': manifest, 'secrets_loaded': loaded}, indent=2) + '\n')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('drill', type=Path, help='drill directory holding the stage subdirectories')
    parser.add_argument('out', type=Path, help='new export directory')
    parser.add_argument('stages', nargs='+', help='stage subdirectory names to export')
    parser.add_argument('--baseline', type=resolve_baseline, default=DEFAULT_BASELINE,
                        help='prepared runtime stage of the drilled candidate; the owner fixture is '
                             '<baseline>/private/owner.json (default: the v0.6.4 stage)')
    parser.add_argument('--b2-key', type=bucket_key_argument, default=DEFAULT_B2_KEY,
                        help='dedicated test-bucket key file, or "none" to declare on the record that this '
                             'host holds none — the replacement host never does (default: the v0.6.4 key)')
    args = parser.parse_args(argv)
    # A candidate's key file is named for that candidate. Taking another
    # candidate's baseline while leaving the key at the v0.6.4 default would
    # scan a leftover key — or nothing — and report a covered scan either way.
    # `--b2-key none` is not the default, so a declared-absent key passes here:
    # only the accidental default is refused.
    if args.baseline != DEFAULT_BASELINE.resolve() and args.b2_key == DEFAULT_B2_KEY:
        raise SystemExit(f'refusing export: --baseline {args.baseline} is not the v0.6.4 stage but --b2-key '
                         f'still points at {DEFAULT_B2_KEY}; name this candidate\'s key file, or pass '
                         '--b2-key none to declare on the record that this host holds none')
    return export(args.drill, args.out, args.stages, required=required_sources(args.b2_key), env_file=ENV_FILE,
                  bucket_key_file=args.b2_key, owner_file=owner_path(args.baseline))


if __name__ == '__main__':
    print(json.dumps({'files': len(main(sys.argv[1:]))}))
