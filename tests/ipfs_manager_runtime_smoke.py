#!/usr/bin/env python3
"""Explicit Linux/root/systemd/Docker check of the manager's mounted socket lifecycle.

sudo python3 tests/ipfs_manager_runtime_smoke.py
Creates only random test units/runtime paths and resource-limited, offline clients.
The negative control proves the old unit loses its existing Docker bind mount.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'python:3.13-alpine'


def command(args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=120)


def wait_probe(container, expected):
    code = "import socket; s=socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect('/control/manager.sock'); assert s.recv(2)==b'ok'"
    for _ in range(30):
        result = command(['docker','exec',container,'python3','-c',code],check=False)
        if (result.returncode == 0) == expected:
            return
        time.sleep(0.2)
    raise AssertionError('socket reachability does not match expected '+str(expected))


def wait_host(runtime):
    for _ in range(50):
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(1)
                client.connect(str(runtime/'manager.sock'))
                if client.recv(2) == b'ok': return
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError('restarted host socket did not become ready')


def check_case(preserve):
    name = 'vidra-ipfs-runtime-smoke-' + uuid.uuid4().hex[:12]
    unit = Path('/run/systemd/system') / (name + '.service')
    fixture = Path('/run') / (name + '.py')
    runtime = Path('/run') / name
    state = Path('/var/lib') / name
    container_created = False
    loaded = False
    try:
        fixture.write_text("""import os, socket
from pathlib import Path
p=Path('/run/""" + name + """/manager.sock')
if p.exists(): p.unlink()
s=socket.socket(socket.AF_UNIX); s.bind(str(p)); os.chown(p,0,10001); os.chmod(p,0o660); s.listen()
while True:
 c,_=s.accept()
 with c: c.sendall(b'ok')
""")
        source = (ROOT/'deploy/vidra-ipfs-manager.service').read_text()
        source = source.replace('ExecStart=/usr/bin/python3 /usr/local/lib/vidra/ipfs-manager.py',
                                'ExecStart=/usr/bin/python3 '+str(fixture))
        source = source.replace('vidra-ipfs-control',name).replace('@@IPFS_REPO@@',str(runtime))
        source = source.replace('RuntimeDirectoryPreserve=yes', 'RuntimeDirectoryPreserve='+preserve)
        unit.write_text(source)
        loaded = True
        command(['systemctl','daemon-reload'])
        command(['systemctl','start',unit.name])
        wait_host(runtime)
        inode = runtime.stat().st_ino
        container_created = True
        command(['docker','run','-d','--name',name,'--network','none','--read-only',
                 '--user','10001:10001','--cap-drop','ALL','--security-opt','no-new-privileges',
                 '--pids-limit','32','--memory','64m','--cpus','0.25',
                 '--mount','type=bind,src='+str(runtime)+',dst=/control,readonly',
                 IMAGE,'python3','-c','import time; time.sleep(180)'])
        wait_probe(name,True)
        command(['systemctl','stop',unit.name])
        if preserve == 'yes':
            assert runtime.stat().st_ino == inode, 'preserved directory inode changed on stop'
        else:
            assert not runtime.exists(), 'negative control did not remove runtime directory'
        command(['systemctl','start',unit.name])
        wait_host(runtime)
        wait_probe(name,preserve == 'yes')
        if preserve == 'yes':
            assert runtime.stat().st_ino == inode, 'directory inode changed across start'
        return {'preserve':preserve,'existing_container_socket_reachable':preserve == 'yes',
                'directory_preserved':preserve == 'yes'}
    finally:
        errors=[]
        if container_created:
            if command(['docker','container','inspect',name],check=False).returncode == 0:
                if command(['docker','rm','-f',name],check=False).returncode: errors.append('container')
        if loaded:
            if command(['systemctl','stop',unit.name],check=False).returncode: errors.append('unit stop')
            unit.unlink(missing_ok=True)
            if command(['systemctl','daemon-reload'],check=False).returncode: errors.append('unit reload')
            command(['systemctl','reset-failed',unit.name],check=False)
        fixture.unlink(missing_ok=True)
        for directory in (runtime,state):
            if directory.exists(): shutil.rmtree(directory)
        if errors: raise RuntimeError('isolated test cleanup failed: '+', '.join(errors))


if __name__ == '__main__':
    if os.geteuid()!=0 or not Path('/run/systemd/system').is_dir():
        raise SystemExit('requires Linux root, systemd and Docker')
    if command(['docker','image','inspect',IMAGE],check=False).returncode:
        command(['docker','pull',IMAGE])
    print(json.dumps({'ok':True,'scope':'isolated systemd socket only; no production manager or IPFS publication',
                      'cases':[check_case('no'),check_case('yes')]},indent=2))
