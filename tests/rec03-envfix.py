"""REC03 fixture-only scan opt-out and explicit documented resource profile."""
import os
from pathlib import Path
import re
import sys
import tempfile


def apply(path, resource_profile=''):
    # Historical operator invocations only change the scan posture. A typo in
    # the optional profile must fail before reading or rewriting their env.
    if resource_profile not in ('', 'small'):
        raise ValueError('unknown REC03 resource profile')
    path = Path(path)
    text = path.read_text()

    def setting(key, value):
        nonlocal text
        pattern = rf'(?m)^{re.escape(key)}=.*$'
        if re.search(pattern, text):
            text = re.sub(pattern, f'{key}={value}', text)
        else:
            text = text.rstrip('\n') + f'\n{key}={value}\n'

    # setup --scan=false drops the profile but retains the scanner address.
    setting('MALWARE_SCAN_MODE', 'disabled')
    text = re.sub(r'(?m)^CLAMAV_ADDR=.*$',
                  '# CLAMAV_ADDR unset for the REC-03 drill: unscanned on purpose (beta posture)', text)
    if resource_profile == 'small':
        # deploy/README.md's 4-vCPU / 8-GB floor; the shipped overlay's
        # defaults target 8 vCPUs and cannot start on a four-core runner.
        for key, value in (('API_CPUS', '3.0'), ('API_MEM_LIMIT', '4g'),
                           ('POSTGRES_SHARED_BUFFERS', '512MB'),
                           ('POSTGRES_EFFECTIVE_CACHE_SIZE', '3GB')):
            setting(key, value)

    temporary = None
    try:
        # Create private, then atomically replace: never expose a public
        # intermediate copy of the generated database/application secrets.
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent,
                                         prefix=path.name + '.', delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    profile = os.environ.get('REC03_RESOURCE_PROFILE', '')
    try:
        apply('/opt/vidra/env/production.env', profile)
    except ValueError:
        print('REC03 resource profile refused', file=sys.stderr)
        return 1
    except OSError:
        print('REC03 fixture env update failed', file=sys.stderr)
        return 1
    print('scan posture and small resource profile applied' if profile else 'scan posture applied')
    return 0


if __name__ == '__main__':
    sys.exit(main())
