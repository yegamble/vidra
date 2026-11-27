#!/usr/bin/env python3
"""Check that deployed services can consume every core configuration key."""

import json
import sys
from pathlib import Path

REFERENCE_KEY = 'IPFS_REFERENCE_STATUS_FILE'
REFERENCE_DIR = '/run/vidra-reference-status'


def reference_mounts(service, source):
    return [mount for mount in service.get('volumes', [])
            if mount.get('target') == REFERENCE_DIR or mount.get('source') == source]


def check(default, enabled, source, go_keys):
    if not go_keys:
        raise ValueError('core configuration inventory is empty')
    for services in (default, enabled):
        if not {'api', 'worker'} <= services.keys():
            raise ValueError('the rendered model must contain both api and worker')

    # The reference observation is local to the API. Only exempt this key from
    # shared defaults after proving the actual optional consumer and its mount.
    for mode, services in (('default', default), ('enabled', enabled)):
        for name, service in services.items():
            env = service.get('environment') or {}
            mounts = reference_mounts(service, source)
            if mode == 'enabled' and name == 'api':
                if env.get(REFERENCE_KEY) != REFERENCE_DIR + '/status.json':
                    raise ValueError('the enabled API must read its mounted reference status file')
                if len(mounts) != 1:
                    raise ValueError('the enabled API must mount exactly one reference status directory')
                mount = mounts[0]
                if (mount.get('type') != 'bind' or mount.get('source') != source or
                        mount.get('target') != REFERENCE_DIR or mount.get('read_only') is not True or
                        mount.get('bind', {}).get('create_host_path', False)):
                    raise ValueError('the enabled API needs the configured read-only reference directory')
            elif REFERENCE_KEY in env or mounts:
                raise ValueError(f'{mode} {name} unexpectedly exposes the reference status input')

    shared = go_keys - {REFERENCE_KEY}
    envs = {name: set(default[name].get('environment') or {}) for name in ('api', 'worker')}
    for name, keys in envs.items():
        enabled_keys = set(enabled[name].get('environment') or {}) - {REFERENCE_KEY}
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
    base, overlay, source, keys = sys.argv[1:]
    try:
        count = check(json.loads(Path(base).read_text())['services'],
                      json.loads(Path(overlay).read_text())['services'], source,
                      set(Path(keys).read_text().split()))
    except ValueError as error:
        sys.exit(f'::error::{error}')
    print(f'OK: {count} shared config keys reach both services; the reference status input is opt-in and API-only.')
