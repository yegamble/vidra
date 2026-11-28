#!/usr/bin/env python3
"""Check that deployed services can consume every core configuration key."""

import json
import sys
from pathlib import Path, PurePosixPath

REFERENCE_KEY = 'IPFS_REFERENCE_STATUS_FILE'
REFERENCE_DIR = '/run/vidra-reference-status'
PLAYBACK_KEY = 'IPFS_REFERENCE_PLAYBACK_SOCKET'


def reference_mounts(service, source, directory, basename):
    host_file = PurePosixPath(source, basename)
    return [mount for mount in service.get('volumes', [])
            if mount.get('target') in (directory, str(PurePosixPath(directory, basename))) or
            (mount.get('type') == 'bind' and
             PurePosixPath(mount['source']) in (host_file, *host_file.parents))]


def check(default, enabled, source, go_keys, playback_source=None):
    if not go_keys:
        raise ValueError('core configuration inventory is empty')
    for services in (default, enabled):
        if not {'api', 'worker'} <= services.keys():
            raise ValueError('the rendered model must contain both api and worker')

    inputs = {REFERENCE_KEY: (source, REFERENCE_DIR, 'status.json')}
    if playback_source is not None:
        inputs[PLAYBACK_KEY] = (playback_source, '/run/vidra-reference-playback', 'playback.sock')
    # Exempt a key from the shared set only after proving its actual mount,
    # consumer and absence from every other service.
    for key, (host, directory, basename) in inputs.items():
        for mode, services in (('default', default), ('enabled', enabled)):
            for name, service in services.items():
                env = service.get('environment') or {}
                mounts = reference_mounts(service, host, directory, basename)
                if mode == 'enabled' and name == 'api':
                    if env.get(key) != directory + '/' + basename or len(mounts) != 1:
                        raise ValueError(f'the enabled API must read {key} at its single mounted path')
                    mount = mounts[0]
                    if (mount.get('type') != 'bind' or mount.get('source') != host or
                            mount.get('target') != directory or mount.get('read_only') is not True or
                            mount.get('bind', {}).get('create_host_path', False)):
                        raise ValueError(f'the enabled API needs the configured read-only directory for {key}')
                elif key in env or mounts:
                    raise ValueError(f'{mode} {name} unexpectedly exposes {key}')

    shared = go_keys - inputs.keys()
    envs = {name: set(default[name].get('environment') or {}) for name in ('api', 'worker')}
    for name, keys in envs.items():
        enabled_keys = set(enabled[name].get('environment') or {}) - inputs.keys()
        if enabled_keys != keys:
            raise ValueError(f'the reference overlay changed shared {name} configuration keys')
        missing = sorted(shared - keys)
        if missing:
            raise ValueError(f'core config missing from the rendered {name} environment: ' + ', '.join(missing))
    if envs['api'] != envs['worker']:
        raise ValueError('default API/worker environment key mismatch: ' +
                         ', '.join(sorted(envs['api'] ^ envs['worker'])))
    return len(shared)


if __name__ == '__main__':
    base, overlay, source, keys, playback = sys.argv[1:]
    try:
        count = check(json.loads(Path(base).read_text())['services'],
                      json.loads(Path(overlay).read_text())['services'], source,
                      set(Path(keys).read_text().split()), playback)
    except ValueError as error:
        sys.exit(f'::error::{error}')
    print(f'OK: {count} shared config keys reach both services; the reference status and playback inputs are opt-in and API-only.')
