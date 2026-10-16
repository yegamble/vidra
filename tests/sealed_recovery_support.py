"""Published-image/synthetic-data boundaries; never a production backup reader."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from blank_server_smoke import require, validate_candidate

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sealed_mapping', ROOT / 'deploy/release-mapping.py')
mapping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping)
MEMBERS = {'backup.dump.gz', 'config.tar.gz', 'fixture.json', 'proof.json'}
MAX_HANDOFF = 128 * 1024 * 1024
# PUBLIC TEST MATERIAL, deliberately unrelated to every generated application
# KEK. Anyone can decrypt these synthetic fixtures. NEVER use for real backups.
RECIPIENT = 'age19dp4ac7wgelyuxe99qng3vp0xxfm29n5wsjpxsfxpgs20ktnqeeqnq6ye2'
IDENTITY = 'AGE-SECRET-KEY-12RXAWEFDKZ8JV2JM6GSYCV4XGQAKTCJSKTTKHHMZQST2H4972N8SSQP057'


def head(root):
    # Root runs the isolated host driver; checkout ownership remains runner's.
    # Trust exactly this checkout for this read, never global/wildcard paths.
    return subprocess.check_output(['git', '-c', 'safe.directory=' + str(root.resolve()),
                                    '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()


def published(root, tag, record_commit):
    """Bind one immutable record checkout to its real PASS preflight evidence."""
    require(re.fullmatch(r'[0-9a-f]{40}', record_commit), 'record commit must be immutable')
    require(mapping.STRICT_RELEASE_TAG.fullmatch(tag), 'release tag must be strict semver')
    require(head(root) == record_commit, 'record checkout differs')
    path = root / 'releases' / (tag + '.json')
    record = json.loads(path.read_text())
    require(not mapping.validate(path, record), 'invalid release record')
    expected = f'docs/evidence/release-{tag}-verification/manifest.json'
    require(record.get('evidence') == expected, 'unexpected preflight evidence path')
    candidate = json.loads((root / expected).read_text())
    validate_candidate(candidate)
    require(candidate['tag'] == tag and candidate['platform'] == 'linux/amd64', 'wrong preflight candidate')
    require(candidate['repositories']['vidra']['revision'] == record['meta_commit'], 'meta provenance differs')
    candidate = copy.deepcopy(candidate)
    for role, component in record['components'].items():
        name, image = 'vidra-' + role, component['image']
        frozen = candidate['repositories'][name]
        require(frozen['revision'] == component['commit'] and frozen['tag'] == component['tag'],
                'component source differs')
        digest = image['platforms']['linux/amd64']
        require(image['repository'] == 'ghcr.io/yegamble/' + name, 'unexpected image repository')
        require(candidate['images'][name]['digest'] in (digest, image['index_digest']), 'image digest differs')
        candidate['images'][name].update(digest=digest, reference=image['repository'] + '@' + digest)
    return record, candidate


def check_vm(facts, boot_id, source_boot=None):
    """Hosted VMs may have Docker installed; existing deployments stay refused."""
    allowed = {'docker', 'containerd', 'podman', '/var/lib/docker', '/var/lib/containerd', '/etc/docker'}
    require(facts['system'] == 'Linux' and facts['architecture'] == 'x86_64'
            and facts['os'].get('ID') == 'ubuntu' and facts['os'].get('VERSION_ID') == '24.04',
            'native Ubuntu 24.04 AMD64 VM required')
    require(facts['root'] and facts['systemd'] and not facts['container'], 'native root systemd VM required')
    require(not set(facts['existing']) - allowed, 'existing deployment refused')
    require(bool(boot_id) and (source_boot is None or boot_id != source_boot), 'replacement must be another VM')


def inspect_handoff(data):
    """Decode a fixed, bounded archive without extracting paths supplied by it."""
    require(len(data) <= MAX_HANDOFF, 'handoff is oversized')
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as archive:
            members = archive.getmembers()
            require(len(members) == len(MEMBERS) and {m.name for m in members} == MEMBERS,
                    'unexpected handoff members')
            require(all(m.isfile() for m in members) and sum(m.size for m in members) <= MAX_HANDOFF,
                    'invalid handoff member type or size')
            return {m.name: archive.extractfile(m).read() for m in members}
    except (tarfile.TarError, OSError) as error:
        raise ValueError('invalid handoff archive') from error


def pack_handoff(files, destination, env):
    require(set(files) == MEMBERS and not destination.exists(), 'invalid handoff destination or files')
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, source in sorted(files.items()):
            require(source.is_file() and not source.is_symlink(), 'handoff source must be a regular file')
            info = archive.gettarinfo(str(source), arcname=name)
            info.mode = 0o600
            with source.open('rb') as handle:
                archive.addfile(info, handle)
    data = stream.getvalue()
    inspect_handoff(data)
    encrypted = subprocess.run(['age', '-r', RECIPIENT], input=data, capture_output=True, check=True, env=env).stdout
    with destination.open('xb') as handle:
        handle.write(encrypted)
    destination.chmod(0o600)


def unpack_handoff(source, destination, env):
    require(not destination.exists() and source.is_file() and not source.is_symlink(), 'invalid handoff input')
    require(source.stat().st_size <= MAX_HANDOFF, 'encrypted handoff is oversized')
    with tempfile.TemporaryDirectory() as temporary:
        identity = Path(temporary) / 'public-test-identity'
        identity.write_text(IDENTITY + '\n')
        identity.chmod(0o600)
        data = subprocess.run(['age', '-d', '-i', str(identity), str(source)], capture_output=True,
                              check=True, env=env).stdout
    members = inspect_handoff(data)
    destination.mkdir(mode=0o700)
    for name, content in members.items():
        path = destination / name
        with path.open('xb') as handle:
            handle.write(content)
        path.chmod(0o600)
    return destination
