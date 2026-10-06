"""Offline packaging smoke test; never connects to a device or uses game data."""
import hashlib
from pathlib import Path
import tempfile
import sys
import subprocess

def smoke_test(resources: Path) -> dict:
    from . import __version__
    from .gui import App
    from .install import SOURCE_COMMIT
    from .ssh import Settings
    names = ('remote_install.py', 'steam_shortcut.py', 'steam_live.py', 'steam_notes.py', 'build-native.sh',
             'frame-controls.patch', 'ui/app-icon.png', 'ui/app-icon.ico',
             'artwork/halo-ce-cover.jpg', 'artwork/halo-ce-landscape.png',
             'artwork/halo-ce-thumbnail.png', 'artwork/halo-ce-hero.jpg',
             'artwork/halo-ce-logo.png', 'artwork/halo-ce-icon.png')
    hashes = {}
    usb_bundled = getattr(sys, 'frozen', False)
    if usb_bundled:
        names += ('usb/adb.exe', 'usb/AdbWinApi.dll', 'usb/AdbWinUsbApi.dll',
                  'usb/NOTICE.txt', 'usb/manifest.json')
    for name in names:
        path = resources / name
        if not path.is_file():
            raise RuntimeError('Packaged resource missing: ' + name)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not (resources / 'licenses').is_dir():
        raise RuntimeError('Packaged dependency notices missing')
    if 'smoke-secret' in repr(Settings('frame', 'smoke-secret')):
        raise RuntimeError('Password exposed in Settings repr')
    if usb_bundled:
        from .usb import bundled_adb
        helper = bundled_adb()
        result = subprocess.run([str(helper), 'version'], capture_output=True, text=True,
                                timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or 'Version 37.0.1-' not in result.stdout:
            raise RuntimeError('Packaged USB helper did not run its offline version check')
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
            if str(app.progress['mode']) != 'determinate':
                raise RuntimeError('Packaged progress bar is not determinate')
            if {choice.value for choice in app.mode_choices} != {'install', 'repair', 'library', 'uninstall'}:
                raise RuntimeError('Packaged operation choices are incomplete')
            if {choice.value for choice in app.transport_choices} != {'network', 'usb'}:
                raise RuntimeError('Packaged connection choices are incomplete')
            if app.music.muted or hasattr(app, 'music_button') or hasattr(app, '_toggle_music'):
                raise RuntimeError('Packaged music behavior does not match this release')
            app.host.set('frame')
            app.password.set('smoke-secret')
            if app._settings().close_steam_for_shortcut:
                raise RuntimeError('Packaged setup must keep Steam Home running')
            app.transport.set('usb')
            app.usb_serial.set('smoke-usb-device')
            app.fingerprints = {'usb:smoke-usb-device': 'SHA256:smoke-usb'}
            settings = app._settings()
            if (settings.transport != 'usb' or settings.host_identity != 'usb:smoke-usb-device'
                    or settings.known_host_fingerprint != 'SHA256:smoke-usb'):
                raise RuntimeError('Packaged USB settings did not preserve device identity')
            if settings.close_steam_for_shortcut:
                raise RuntimeError('Packaged USB setup must keep Steam Home running')
            settings.password = ''
            app.password.set('')
            app.mode.set('library')
            app.source.set('')
            app.authorized.set(False)
            app._show_page(0)
            app._continue()
            if (app.current_page != 1 or app.data_panel.winfo_manager()
                    or app.data_consent.winfo_manager() or not app.library_card.winfo_manager()
                    or 'No ISO or rebuild' not in '\n'.join(
                        str(widget.cget('text')) for widget in app.library_card.winfo_children()[0].winfo_children()
                        if 'text' in widget.keys())):
                raise RuntimeError('Packaged Steam info update requires game data or lost its no-rebuild guidance')
        finally:
            for callback in app.tk.call('after', 'info'):
                app.after_cancel(callback)
            app.destroy()
    if not valid:
        raise RuntimeError('Installer window did not initialize')
    return {'ok': True, 'version': __version__, 'sourceCommit': SOURCE_COMMIT,
            'resources': hashes, 'guiInitialized': True,
            'guiPagesInitialized': pages_initialized,
            'determinateProgress': True, 'uninstallAvailable': True,
            'automaticMusicWithoutToggle': True,
            'keepsSteamSessionRunning': True,
            'usbTransferAvailable': True,
            'steamInfoUpdateWithoutRebuild': True,
            'steamDescriptionUsesNotes': True,
            'usbToolsBundled': usb_bundled,
            'passwordReprRedacted': True, 'networkConnections': 0}
