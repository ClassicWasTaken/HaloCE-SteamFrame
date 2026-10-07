"""Offline packaging smoke test; never connects to a device or uses game data."""
import hashlib
from pathlib import Path
import tempfile
import sys
import subprocess

def smoke_test(resources: Path) -> dict:
    from . import __version__
    from .gui import App, APP_TITLE, CONTENT_DISCLOSURE
    from .install import InstallResult, SOURCE_COMMIT
    from . import gui
    from .ssh import Settings
    names = ('remote_install.py', 'frame_storage.py', 'steam_shortcut.py', 'steam_live.py', 'steam_notes.py', 'build-native.sh',
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
            if app.title() != APP_TITLE or CONTENT_DISCLOSURE not in app.data_disclosure.cget('text'):
                raise RuntimeError('Packaged community mod installer title or content disclosure is missing')
            if str(app.progress['mode']) != 'determinate':
                raise RuntimeError('Packaged progress bar is not determinate')
            if {choice.value for choice in app.mode_choices} != {'install', 'repair', 'uninstall'}:
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
            if {choice.value for choice in app.storage_choices} != {'internal', 'sd'}:
                raise RuntimeError('Packaged storage choices are incomplete')
            card_id = 'sd:' + 'a' * 32
            card_path = '/run/media/steamos/smoke-card/Games/HaloCENativeVR'
            card = {'id': card_id, 'kind': 'sd', 'label': 'SD smoke test',
                    'mountPath': '/run/media/steamos/smoke-card', 'gamePath': card_path,
                    'cachePath': '/run/media/steamos/smoke-card/.halo-frame-installer',
                    'freeBytes': 24 * 1024**3, 'installed': True}
            app._apply_storage_inventory((card,), app._storage_identity())
            app.storage_kind.set('sd')
            if app._settings().storage_id != card_id or card_path not in app.summary_storage.get():
                raise RuntimeError('Packaged SD storage selection was not carried into settings and summary')
            app.host.set('another-frame')
            try:
                app._settings()
            except ValueError:
                pass
            else:
                raise RuntimeError('Packaged SD selection survived a connection identity change')
            app.storage_kind.set('internal')
            settings.password = ''
            app.password.set('')
            for mode in ('install', 'repair'):
                app.mode.set(mode)
                guidance = app.summary_note.get()
                if ('Steam artwork and game Notes are added automatically' not in guidance
                        or hasattr(app, 'library_card')):
                    raise RuntimeError('Packaged install/repair lost automatic Steam info setup')
            # Exercise the reported icon-readback case in the packaged GUI,
            # without opening a dialog or connecting to a device.
            dialogs = []
            showinfo = gui.messagebox.showinfo
            gui.messagebox.showinfo = lambda title, message, **kwargs: dialogs.append((title, message))
            try:
                for repaired in (False, True):
                    app.operation = 'install'
                    app.progress_state.reset()
                    app.events.put(('complete', InstallResult(
                        '/home/steamos/Games/HaloCENativeVR', True,
                        {'status': 'added', 'artwork': {'status': 'unchanged',
                            'icon': {'status': 'manual',
                                     'reason': 'Steam shortcut icon has not loaded yet.'}},
                         'notes': {'status': 'added'}}, None, repaired=repaired)))
                    app._drain()
                    if (float(app.progress['value']) != 100 or app.phase.get() != 'Complete'
                            or app.retry_button.winfo_manager()
                            or dialogs[-1][0] != 'Setup complete'
                            or 'icon' in dialogs[-1][1].lower()):
                        raise RuntimeError('Packaged successful setup was blocked by its optional Steam icon')
            finally:
                gui.messagebox.showinfo = showinfo
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
            'steamInfoAutomaticOnInstall': True,
            'steamDescriptionUsesNotes': True,
            'optionalSteamIconNonBlocking': True,
            'sdCardInstallAvailable': True,
            'storageDiscoveryRequiredForSD': True,
            'usbToolsBundled': usb_bundled,
            'passwordReprRedacted': True, 'networkConnections': 0}
