"""Exercise the actual rootless build flags on Linux, without any game data."""
from __future__ import annotations

import importlib.util
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != 'linux' or os.getuid() == 0:
        raise SystemExit('Run this check as a regular Linux user with rootless Podman.')
    info = json.loads(subprocess.check_output(['podman', 'info', '--format', 'json'], text=True))
    if not info.get('host', {}).get('security', {}).get('rootless', False):
        raise SystemExit('This check requires rootless Podman.')
    print(json.dumps({'architecture': platform.machine(), 'hostUid': os.getuid(),
                      'hostGid': os.getgid(), 'rootless': True,
                      'idMappings': info.get('host', {}).get('idMappings')}), flush=True)
    spec = importlib.util.spec_from_file_location('remote_helper', ROOT / 'resources/remote_install.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    with tempfile.TemporaryDirectory(prefix='halo-container-check-') as scratch:
        directory = Path(scratch)
        script = r'''set -euo pipefail
test "$(id -u)" = 0
test "$(awk '/NoNewPrivs:/ {print $2}' /proc/self/status)" = 1
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates python3
python3 - <<'PY'
import os
from pathlib import Path
original_groups = os.getgroups()
os.setgroups([65534])
os.setegid(65534)
os.seteuid(100)
os.seteuid(0)
os.setegid(0)
os.setgroups(original_groups)
probe = Path('/build/container-permissions-ok')
probe.write_text('rootless apt and UID/GID changes passed\n')
os.chown(probe, 100, 65534)
os.chown(probe, 0, 0)
PY
'''
        args = helper.build_container_args(uuid.uuid4().hex, directory, ['/bin/bash', '-euc', script])
        subprocess.run(args, check=True, timeout=600)
        proof = directory / 'container-permissions-ok'
        if proof.stat().st_uid != os.getuid() or proof.stat().st_gid != os.getgid():
            raise RuntimeError('Container output was not mapped back to the host user.')
        print('Rootless build container: apt, setgroups, seteuid, setegid, chown and host file ownership passed.')


if __name__ == '__main__':
    main()
