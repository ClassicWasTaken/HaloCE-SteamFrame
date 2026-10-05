"""Offline packaging smoke test; never connects to a device or uses game data."""
import hashlib
from pathlib import Path
import tempfile

def smoke_test(resources: Path) -> dict:
    from . import __version__
    from .gui import App
    from .install import SOURCE_COMMIT
    from .ssh import Settings
    names = ('remote_install.py', 'steam_shortcut.py', 'build-native.sh',
             'frame-controls.patch', 'ui/app-icon.png', 'ui/app-icon.ico',
             'artwork/halo-ce-cover.jpg', 'artwork/halo-ce-landscape.png',
             'artwork/halo-ce-thumbnail.png')
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
        pages_initialized = []
        try:
            app.withdraw()
            for index, name in enumerate(('gameData', 'connection', 'install')):
                app._show_page(index)
                app.update_idletasks()
                if app.current_page != index:
                    raise RuntimeError('Installer page did not initialize: ' + name)
                pages_initialized.append(name)
            valid = (bool(app.asset_status.get()) and app.log.winfo_reqheight() > 1
                     and hasattr(app, '_game_cover') and hasattr(app, 'music'))
        finally:
            for callback in app.tk.call('after', 'info'):
                app.after_cancel(callback)
            app.destroy()
    if not valid:
        raise RuntimeError('Installer window did not initialize')
    return {'ok': True, 'version': __version__, 'sourceCommit': SOURCE_COMMIT,
            'resources': hashes, 'guiInitialized': True,
            'guiPagesInitialized': pages_initialized,
            'passwordReprRedacted': True, 'networkConnections': 0}
