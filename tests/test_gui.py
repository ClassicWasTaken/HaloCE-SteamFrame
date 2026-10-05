import sys
import json
import subprocess
from pathlib import Path
import pytest

WINDOWS_GUI = pytest.mark.skipif(sys.platform != 'win32', reason='Windows Tk packaging smoke test')


def _disabled(widget):
    return str(widget.cget('state')) == 'disabled'


def _display_text(widget):
    """Read visible captions, including StringVar-backed result labels."""
    values = []
    for option in ('text', 'textvariable'):
        if option in widget.keys():
            value = widget.cget(option)
            if option == 'textvariable' and value:
                value = ('<masked>' if 'show' in widget.keys() and widget.cget('show')
                         else widget.getvar(value))
            values.append(str(value))
    for child in widget.winfo_children():
        values.extend(_display_text(child))
    return values


@pytest.fixture(scope='module')
def app_window(tmp_path_factory):
    from halo_frame_installer import gui
    # Tk applications use one root/interpreter; reset its state between scenarios.
    instance = gui.App(tmp_path_factory.mktemp('gui') / 'state')
    instance.withdraw()
    instance.update_idletasks()
    try:
        yield instance
    finally:
        for callback in instance.tk.call('after', 'info'):
            instance.after_cancel(callback)
        instance.destroy()


@pytest.fixture
def app(app_window, monkeypatch):
    from halo_frame_installer import gui
    dialogs = []
    for name in ('showinfo', 'showerror'):
        monkeypatch.setattr(gui.messagebox, name,
                            lambda title, message, **kwargs: dialogs.append((title, message)))
    monkeypatch.setattr(gui.messagebox, 'askyesno', lambda *args, **kwargs: True)

    def forbidden_network(*args, **kwargs):
        raise AssertionError('The GUI verification must not open an SSH connection.')

    monkeypatch.setattr(gui.SSHConnection, 'connect', forbidden_network)
    instance = app_window
    for callback in instance.tk.call('after', 'info'):
        instance.after_cancel(callback)
    instance.events.queue.clear()
    instance.last_result = None
    instance.source.set('')
    instance.host.set('frame')
    instance.port.set('22')
    instance.password.set('')
    instance.password_to_redact = ''
    instance.authorized.set(False)
    instance.steam_closed.set(False)
    instance.mode.set('install')
    instance.max_page = 0
    instance._set_busy(False)
    instance._show_page(0)
    instance.progress.stop()
    instance.progress.configure(mode='determinate', value=0)
    instance.log_lines.clear()
    instance.log.configure(state='normal')
    instance.log.delete('1.0', 'end')
    instance.log.configure(state='disabled')
    instance.withdraw()
    instance.update_idletasks()
    instance._test_dialogs = dialogs
    try:
        yield instance
    finally:
        for callback in instance.tk.call('after', 'info'):
            instance.after_cancel(callback)
        instance.password.set('')
        instance.password_to_redact = ''


class _ImmediateThread:
    """Run an injected offline installer in the calling Tk thread."""
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()

def test_control_guide_matches_expected_layout():
    from halo_frame_installer.gui import CONTROLS
    for action in ('Jump', 'Melee', 'Reload / use', 'Change weapon',
                   'LB  Change grenade', 'RB  Flashlight', 'Both grips  Recenter'):
        assert action in CONTROLS


@WINDOWS_GUI
def test_long_build_failure_has_readable_dialog_and_complete_redacted_log(app):
    app.password_to_redact = 'offline-secret'
    details = 'Native build failed. The existing game was kept.\n' + ('compiler diagnostic offline-secret\n' * 200)
    app.events.put(('error', details))
    app._drain()
    _, message = app._test_dialogs[-1]
    assert message.startswith('Native build failed. The existing game was kept.')
    assert len(message) < 600 and 'Show activity' in message and 'Save log' in message
    assert 'offline-secret' not in message
    assert '\n'.join(app.log_lines).count('compiler diagnostic [redacted]') == 200

@WINDOWS_GUI
def test_gui_offline_smoke():
    resources = Path(__file__).resolve().parents[1] / 'resources'
    code = ('import json, sys; from pathlib import Path; '
            'resources = Path(sys.argv[1]); '
            'sys.path.insert(0, str(resources.parent / "src")); '
            'from halo_frame_installer.selftest import smoke_test; '
            'print(json.dumps(smoke_test(resources)))')
    report = subprocess.run([sys.executable, '-c', code, str(resources)],
                            capture_output=True, text=True, check=True)
    result = json.loads(report.stdout)
    assert result['ok'] and result['guiInitialized']
    from halo_frame_installer import __version__
    assert result['version'] == __version__
    assert result['guiPagesInitialized'] == ['gameData', 'connection', 'install']
    assert result['networkConnections'] == 0


@WINDOWS_GUI
def test_pages_preserve_inputs_and_mode(app):
    app.source.set('X:/my-original-xbox-image.iso')
    app.host.set('192.0.2.24')
    app.port.set('2222')
    app.password.set('offline-secret')
    app.authorized.set(True)
    app.steam_closed.set(True)
    app.mode.set('repair')
    for index in (1, 2, 0, 2, 1, 0):
        app._show_page(index)
        app.update_idletasks()
        assert app.current_page == index
        assert (app.source.get(), app.host.get(), app.port.get(), app.password.get(),
                app.authorized.get(), app.steam_closed.get(), app.mode.get()) == (
                    'X:/my-original-xbox-image.iso', '192.0.2.24', '2222',
                    'offline-secret', True, True, 'repair')


@WINDOWS_GUI
def test_continue_requires_authorized_data_but_allows_repair_without_image(app):
    app._nav_to(2)
    assert app.current_page == 0
    assert _disabled(app.nav_buttons[2])
    app.mode.set('install')
    app._continue()
    assert app.current_page == 0
    assert app._test_dialogs
    app.mode.set('repair')
    app._continue()
    assert app.current_page == 0  # Existing data still requires authorization.
    app.authorized.set(True)
    app._continue()
    assert app.current_page == 1
    assert not app.source.get()
    app.password.set('offline-secret')
    app.port.set('invalid-port')
    app.steam_closed.set(True)
    app._continue()
    assert app.current_page == 1
    app.port.set('22')
    app.steam_closed.set(False)
    app._continue()
    assert app.current_page == 1
    app.steam_closed.set(True)
    app._continue()
    assert app.current_page == 2


@WINDOWS_GUI
def test_busy_disables_navigation_and_inputs_until_idle(app):
    app.source.set('X:/my-original-xbox-image.iso')
    app.authorized.set(True)
    app.password.set('offline-secret')
    app.steam_closed.set(True)
    app._show_page(1)
    app._set_busy(True)
    for control in (*app.nav_buttons, app.back_button, app.primary_button, *app.entries):
        assert _disabled(control)
    assert not _disabled(app.cancel_button)
    app.events.put(('idle',))
    app._drain()
    assert not app.busy
    assert not _disabled(app.primary_button)
    assert not _disabled(app.back_button)
    assert all(not _disabled(control) for control in app.nav_buttons[:2])
    assert _disabled(app.nav_buttons[2])  # The next page remains gated by Continue.
    assert _disabled(app.cancel_button)


@WINDOWS_GUI
def test_repair_uses_existing_maps_and_clears_password(app, monkeypatch):
    from halo_frame_installer import gui, install
    calls = []

    def fake_run(settings, maps_dir, progress, cancel):
        calls.append((maps_dir, settings.adopt_existing_native, settings.password))
        progress('repair', 'Reinstalling program files', 64)
        return install.InstallResult('/home/steamos/Games/HaloCENativeVR', True,
            {'status': 'added', 'appid': 123}, 'SHA256:offline', repaired=True,
            backup_path='/home/steamos/Games/HaloCENativeVR.backup-offline')

    monkeypatch.setattr(install, 'run', fake_run)
    monkeypatch.setattr(gui.threading, 'Thread', _ImmediateThread)
    monkeypatch.setattr(gui, 'inspect_image', lambda *args, **kwargs: pytest.fail('Repair inspected a local image.'))
    monkeypatch.setattr(gui, 'inspect_maps', lambda *args, **kwargs: pytest.fail('Repair inspected a local maps folder.'))
    app.mode.set('repair')
    app.authorized.set(True)
    app.steam_closed.set(True)
    app.password.set('offline-secret')
    app._show_page(2)
    app._install(repair=True)
    app._drain()
    assert calls == [(None, True, 'offline-secret')]
    assert app.last_result.repaired
    assert float(app.progress['value']) == 100
    assert 'repaired' in app.status.get().lower()
    assert not app.password.get()
    assert not app.busy
    assert any('backup-offline' in line for line in app.log_lines)


@WINDOWS_GUI
def test_progress_and_errors_redact_password_on_every_display(app):
    secret = 'offline-secret'
    app.password_to_redact = secret
    app.password.set(secret)
    app._show_page(2)
    app._set_busy(True)
    app.events.put(('progress', 'build ' + secret, 'Compiler diagnostic ' + secret, 38))
    app._drain()
    assert float(app.progress['value']) == 38
    assert secret not in app.status.get()
    assert secret not in '\n'.join(app.log_lines)
    assert secret not in '\n'.join(_display_text(app))
    app.events.put(('error', 'Connection failed: ' + secret))
    app.events.put(('clear_password',))
    app.events.put(('idle',))
    app._drain()
    assert not app.busy
    assert not app.password.get()
    assert any('[redacted]' in line for line in app.log_lines)
    assert secret not in '\n'.join(message for title, message in app._test_dialogs)
    assert secret not in '\n'.join(_display_text(app))


@WINDOWS_GUI
def test_manual_steam_completion_keeps_actionable_instructions_redacted(app):
    from halo_frame_installer.install import InstallResult
    secret = 'offline-secret'
    app.password_to_redact = secret
    app._show_page(2)
    app._set_busy(True)
    result = InstallResult('/home/steamos/Games/HaloCENativeVR', False,
        {'status': 'manual', 'reason': 'Steam is still running. ' + secret,
         'instructions': 'Quit Steam, then click Add to Steam again.'}, None)
    app.events.put(('complete', result))
    app.events.put(('idle',))
    app._drain()
    assert app.last_result.requires_manual_steam_step
    assert 'Add to Steam again' in app.status.get()
    assert not _disabled(app.retry_button)
    assert secret not in app.status.get()
    assert secret not in '\n'.join(app.log_lines)
    assert secret not in '\n'.join(_display_text(app))
    assert secret not in '\n'.join(message for title, message in app._test_dialogs)


@WINDOWS_GUI
def test_minimum_window_keeps_primary_navigation_in_bounds(app):
    width, height = app.minsize()
    app.geometry(f'{width}x{height}')
    app.deiconify()
    for index in range(3):
        app._show_page(index)
        app.update()  # Process native window mapping after deiconify on Windows.
        for control in (*app.nav_buttons, app.primary_button, app.back_button):
            assert control.winfo_ismapped()
            left = control.winfo_rootx() - app.winfo_rootx()
            top = control.winfo_rooty() - app.winfo_rooty()
            assert left >= 0 and top >= 0
            assert left + control.winfo_width() <= app.winfo_width()
            assert top + control.winfo_height() <= app.winfo_height()
