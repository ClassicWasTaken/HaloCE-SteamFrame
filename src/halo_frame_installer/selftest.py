"""Offline packaging smoke test; never connects to a device or uses game data."""
import hashlib
from pathlib import Path
import tempfile

def smoke_test(resources: Path) -> dict:
    from .gui import App
    from .install import SOURCE_COMMIT
    from .ssh import Settings
    names = ('remote_install.py', 'steam_shortcut.py', 'build-native.sh', 'frame-controls.patch')
    hashes = {}
    for name in names:
        path = resources / name
        if not path.is_file():
            raise RuntimeError('Packaged resource missing: ' + name)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not (resources / 'licenses').is_dir():
        raise RuntimeError('Packaged dependency notices missing')
    if 'smoke-secret' in repr(Settings('frame', 'smoke-secret')):
        raise RuntimeError('Password exposed in Settings repr')
    with tempfile.TemporaryDirectory(prefix='halo-frame-smoke-') as tmp:
        app = App(Path(tmp) / 'state')
        app.withdraw()
        app.update_idletasks()
        valid = app.asset_status.get().startswith('Original Xbox') and app.log.winfo_reqheight() > 1
        app.destroy()
    if not valid:
        raise RuntimeError('Installer window did not initialize')
    return {'ok': True, 'sourceCommit': SOURCE_COMMIT, 'resources':hashes,
            'guiInitialized':True, 'passwordReprRedacted':True, 'networkConnections':0}
