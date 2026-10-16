#!/usr/bin/env python3
"""Stop only the fixture origin named by this spike's saved PID and full argv."""
import os
from pathlib import Path
import re
import signal
import subprocess
import sys


def matches(pid, expected):
    if sys.platform == 'linux':
        argv = Path(f'/proc/{pid}/cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        argv = [os.fsdecode(arg) for arg in argv]
        return (len(argv) == len(expected) + 1 and argv[1:] == expected
                and re.fullmatch(r'python(?:3(?:\.\d+)?)?', Path(argv[0]).name, re.IGNORECASE) is not None)
    # macOS has no /proc. ps -ww avoids truncation; compare the complete script
    # and every fixture argument, never a basename or a substring of the command.
    result = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', 'command='],
                            capture_output=True, text=True, check=False)
    if result.returncode == 1 and not result.stdout.strip():
        raise ProcessLookupError(pid)
    command = result.stdout.strip()
    suffix = ' ' + ' '.join(expected)
    if result.returncode or not command.endswith(suffix):
        return False
    interpreter = command[:-len(suffix)]
    return (re.fullmatch(r'python(?:3(?:\.\d+)?)?', Path(interpreter).name, re.IGNORECASE) is not None
            and (interpreter == 'python3' or Path(interpreter).is_file()))


def main():
    pidfile, *expected = sys.argv[1:]
    path = Path(pidfile)
    try:
        value = path.read_text().strip()
    except FileNotFoundError:
        return 0
    if not re.fullmatch(r'[1-9][0-9]*', value) or int(value) <= 1:
        print('Refusing invalid origin PID; no process was signalled.', file=sys.stderr)
        return 1
    pid = int(value)
    handle = None
    try:
        # On Linux a pidfd pins the process identity across inspection/signalling,
        # so PID reuse between these operations cannot target another process.
        if hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'):
            handle = os.pidfd_open(pid)
        if not matches(pid, expected):
            print(f'Refusing PID {pid}: it does not match this spike origin; '
                  'no process was signalled.', file=sys.stderr)
            return 1
        if handle is not None:
            signal.pidfd_send_signal(handle, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, FileNotFoundError):
        pass  # An already-exited fixture needs no signal.
    except (OSError, OverflowError) as error:
        print(f'Could not verify/stop fixture origin: {error}', file=sys.stderr)
        return 1
    finally:
        if handle is not None:
            os.close(handle)
    path.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
