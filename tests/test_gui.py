import sys
import json
import subprocess
from pathlib import Path
import pytest

WINDOWS_GUI = pytest.mark.skipif(sys.platform != 'win32', reason='Windows Tk packaging smoke test')


def _disabled(widget):
    return str(widget.cget('state')) == 'disabled'


def _drain_events(app):
    """Functional assertions wait for all queued events, even when Tk yields."""
    while not app.events.empty():
        app._drain()


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
    instance.transport.set('network')
    instance.adb_path.set('')
    instance.usb_serial.set('')
    instance.fingerprints = {}
    instance.password.set('')
    instance.password_to_redact = ''
    instance.authorized.set(False)
    instance.steam_closed.set(False)
    instance.keep_saves.set(True)
    instance.mode.set('install')
    instance.max_page = 0
    instance.installing = False
    instance.uninstall_committing = False
    instance.operation = None
    instance.cancel.clear()
    if instance.activity_open:
        instance._toggle_activity()
    if instance.advanced_open:
        instance._toggle_advanced()
    instance._set_busy(False)
    instance._show_page(0)
    instance.progress_state.reset()
    instance._display_progress()
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
    _drain_events(app)
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
    assert result['steamInfoUpdateWithoutRebuild'] and result['steamDescriptionUsesNotes']
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
def test_usb_and_network_choices_preserve_inputs_across_pages(app):
    app.host.set('192.0.2.24')
    app.port.set('2222')
    app.adb_path.set('C:/Platform Tools/adb.exe')
    app.usb_serial.set('FRAME-SERIAL')
    app.password.set('offline-secret')
    app.transport.set('usb')
    app._show_page(1)
    app.update_idletasks()
    assert app.usb_panel.winfo_manager() == 'pack'
    assert not app.network_panel.winfo_manager()
    assert app.usb_advanced.winfo_manager() == 'pack'
    assert not app.network_advanced.winfo_manager()
    assert app.summary_frame.get() == 'USB-C cable · FRAME-SERIAL'
    for index in (2, 0, 1):
        app._show_page(index)
        assert app.transport.get() == 'usb'
        assert app.adb_path.get() == 'C:/Platform Tools/adb.exe'
        assert app.usb_serial.get() == 'FRAME-SERIAL'
        assert app.password.get() == 'offline-secret'
    app.transport.set('network')
    assert app.network_panel.winfo_manager() == 'pack'
    assert not app.usb_panel.winfo_manager()
    assert app.network_advanced.winfo_manager() == 'pack'
    assert not app.usb_advanced.winfo_manager()
    assert (app.host.get(), app.port.get()) == ('192.0.2.24', '2222')
    assert app.summary_frame.get() == '192.0.2.24'
    assert 'Wi-Fi and Ethernet' in app.connection_prepare_note.cget('text')


@WINDOWS_GUI
def test_usb_settings_ignore_hidden_network_inputs_and_use_device_fingerprint(app):
    app.host.set('invalid hidden address')
    app.port.set('invalid-port')
    app.password.set('offline-secret')
    app.transport.set('usb')
    app.usb_serial.set(' FRAME-SERIAL ')
    app.adb_path.set(' C:/Platform Tools/adb.exe ')
    app.fingerprints = {'usb:FRAME-SERIAL': 'SHA256:usb', '127.0.0.1:2222': 'SHA256:wrong'}
    settings = app._settings()
    assert settings.transport == 'usb'
    assert settings.port == 22
    assert settings.usb_serial == 'FRAME-SERIAL'
    assert settings.adb_path == 'C:/Platform Tools/adb.exe'
    assert settings.host_identity == 'usb:FRAME-SERIAL'
    assert settings.known_host_fingerprint == 'SHA256:usb'
    assert settings.known_host_fingerprints == app.fingerprints
    assert settings.known_host_fingerprints is not app.fingerprints
    assert settings.close_steam_for_shortcut is False


@WINDOWS_GUI
def test_automatic_usb_selection_supplies_saved_device_fingerprints(app):
    app.password.set('offline-secret')
    app.transport.set('usb')
    app.fingerprints = {'usb:FRAME-SERIAL': 'SHA256:usb'}
    settings = app._settings()
    assert settings.usb_serial is None
    assert settings.adb_path is None
    assert settings.known_host_fingerprint is None
    assert settings.known_host_fingerprints == {'usb:FRAME-SERIAL': 'SHA256:usb'}
    assert app.summary_frame.get() == 'USB-C cable · Detect connected Frame'


@WINDOWS_GUI
def test_trusted_usb_fingerprint_persists_by_serial_without_forwarded_port(app):
    import threading
    ready, answer = threading.Event(), []
    app.events.put(('fingerprint', 'usb:FRAME-SERIAL', 'ssh-ed25519', 'SHA256:usb', 22, ready, answer))
    _drain_events(app)
    assert ready.is_set() and answer == [True]
    assert app.fingerprints == {'usb:FRAME-SERIAL': 'SHA256:usb'}
    assert json.loads(app.state_file.read_text(encoding='utf-8')) == app.fingerprints
    app.events.put(('connected', 'usb:FRAME-SERIAL', 'SHA256:usb'))
    _drain_events(app)
    assert app.fingerprints == {'usb:FRAME-SERIAL': 'SHA256:usb'}
    assert app._load_fingerprints() == app.fingerprints
    assert '127.0.0.1' not in app.state_file.read_text(encoding='utf-8')


@WINDOWS_GUI
def test_network_settings_keep_address_port_and_existing_trust_identity(app):
    app.host.set('192.0.2.24')
    app.port.set('2222')
    app.password.set('offline-secret')
    app.fingerprints = {'192.0.2.24:2222': 'SHA256:network'}
    settings = app._settings()
    assert settings.transport == 'network'
    assert settings.host_identity == '192.0.2.24:2222'
    assert settings.known_host_fingerprint == 'SHA256:network'
    app.events.put(('connected', settings.host_identity, 'SHA256:network'))
    _drain_events(app)
    assert app.fingerprints == {'192.0.2.24:2222': 'SHA256:network'}


@WINDOWS_GUI
def test_connection_worker_remembers_resolved_usb_identity_without_opening_network(app, monkeypatch):
    from halo_frame_installer import gui
    closed = []

    class OfflineConnection:
        host_fingerprint = 'SHA256:usb'

        def __init__(self, settings):
            self.settings = settings

        def connect(self):
            assert self.settings.transport == 'usb'
            self.settings.usb_serial = 'FRAME-SERIAL'

        def run(self, argv, **kwargs):
            assert argv == ['uname', '-m']
            return 'aarch64'

        def close(self):
            closed.append(True)

    monkeypatch.setattr(gui, 'SSHConnection', OfflineConnection)
    monkeypatch.setattr(gui.threading, 'Thread', _ImmediateThread)
    app.transport.set('usb')
    app.password.set('offline-secret')
    app._test_connection()
    _drain_events(app)
    assert closed == [True]
    assert app.fingerprints == {'usb:FRAME-SERIAL': 'SHA256:usb'}
    assert not app.busy
    assert 'Connected to your Frame' in app.connection_status.get()


@WINDOWS_GUI
@pytest.mark.parametrize('connection_fails', [False, True])
def test_connection_cleanup_failure_restores_controls_clears_password_and_never_reports_success(app, monkeypatch, connection_fails):
    from halo_frame_installer import gui
    from halo_frame_installer.ssh import SSHError
    captured = []
    actions = []

    class OfflineConnection:
        host_fingerprint = 'SHA256:usb'

        def __init__(self, settings):
            self.settings = settings
            captured.append(settings)

        def connect(self):
            self.settings.usb_serial = 'FRAME-SERIAL'
            if connection_fails:
                raise SSHError('Offline connection failed.')

        def run(self, argv, **kwargs):
            return 'aarch64'

        def close(self):
            actions.append('close')
            raise SSHError('The USB forward could not be removed: offline-secret')

    monkeypatch.setattr(gui, 'SSHConnection', OfflineConnection)
    monkeypatch.setattr(gui.threading, 'Thread', _ImmediateThread)
    app.transport.set('usb')
    app.password.set('offline-secret')
    app._test_connection()
    assert actions == ['close']
    assert captured[0].password == ''
    queued = list(app.events.queue)
    assert not any(event[0] == 'connected' for event in queued)
    assert queued[-1] == ('idle',)
    _drain_events(app)
    assert not app.busy
    assert not app.password.get()
    assert not _disabled(app.primary_button)
    assert all(not _disabled(choice) for choice in app.transport_choices)
    assert app.fingerprints == {}
    assert 'needs attention' in app.connection_status.get()
    assert 'SSH connection verified' not in '\n'.join(app.log_lines)
    log = '\n'.join(app.log_lines)
    assert 'USB forward could not be removed' in log
    assert 'offline-secret' not in log
    assert 'disconnecting' in log
    assert app._test_dialogs
    if connection_fails:
        assert 'Offline connection failed' in log
    else:
        assert any('disconnecting' in message for _, message in app._test_dialogs)


@WINDOWS_GUI
def test_adb_browse_retains_selection_and_is_disabled_during_setup(app, monkeypatch):
    from halo_frame_installer import gui
    calls = []
    monkeypatch.setattr(gui.filedialog, 'askopenfilename',
        lambda **kwargs: calls.append(kwargs) or 'C:/Platform Tools/adb.exe')
    app.transport.set('usb')
    app._choose_adb()
    assert app.adb_path.get() == 'C:/Platform Tools/adb.exe'
    app._set_busy(True)
    assert all(_disabled(choice) for choice in app.transport_choices)
    assert all(_disabled(entry) for entry in app.entries)
    app._choose_adb()
    assert len(calls) == 1
    for choice in app.transport_choices:
        choice._select()
    assert app.transport.get() == 'usb'
    app._set_busy(False)
    assert all(not _disabled(choice) for choice in app.transport_choices)


@WINDOWS_GUI
def test_usb_help_describes_cable_password_internet_and_official_tools(app):
    import tkinter as tk
    app.transport.set('usb')
    text = '\n'.join(_display_text(app))
    for phrase in ('USB tools are included', 'data-capable USB-C cable',
                   'USB debugging prompt', 'SSH password', 'internet access'):
        assert phrase in text
    app._show_help()
    dialogs = [widget for widget in app.winfo_children() if isinstance(widget, tk.Toplevel)]
    try:
        assert len(dialogs) == 1
        text = '\n'.join(_display_text(dialogs[0]))
        assert 'Developer Mode enabled' in text
        assert 'Wi-Fi or Ethernet network' in text
        from halo_frame_installer.gui import PLATFORM_TOOLS_URL
        assert PLATFORM_TOOLS_URL == 'https://developer.android.com/tools/releases/platform-tools'
    finally:
        for dialog in dialogs:
            dialog.destroy()


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
    _drain_events(app)
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
    _drain_events(app)
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
    _drain_events(app)
    assert float(app.progress['value']) == 0  # Unknown phases cannot corrupt overall progress.
    assert secret not in app.status.get()
    assert secret not in '\n'.join(app.log_lines)
    assert secret not in '\n'.join(_display_text(app))
    app.events.put(('error', 'Connection failed: ' + secret))
    app.events.put(('clear_password',))
    app.events.put(('idle',))
    _drain_events(app)
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
         'instructions': 'Use Steam Add a Non-Steam Game, then click Add to Steam again.'}, None)
    app.events.put(('complete', result))
    app.events.put(('idle',))
    _drain_events(app)
    assert app.last_result.requires_manual_steam_step
    assert float(app.progress['value']) == 99
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


@WINDOWS_GUI
def test_real_phase_progress_stays_determinate_and_details_do_not_replace_status(app):
    app.installing = True
    app.password_to_redact = 'offline-secret'
    app._show_page(2)
    app._begin_setup_progress()
    app.events.put(('progress', 'reuse', 'All retained maps verified.', 100))
    app.events.put(('progress', 'build', 'Pulling the build container.', None))
    app.events.put(('progress', 'compile', 'Completed 40 of 100 build tasks.', 40))
    app.events.put(('progress', 'detail', 'compile: [40/100] Building offline-secret.cpp', None))
    _drain_events(app)
    assert str(app.progress.cget('mode')) == 'determinate'
    assert float(app.progress['value']) == pytest.approx(79.8)
    assert app.progress_label.get() == '79%'
    assert app.phase.get() == 'Compiling Halo and VR support'
    assert app.status.get() == 'Completed 40 of 100 build tasks.'
    assert app.log_lines[-1] == 'compile: [40/100] Building [redacted].cpp'
    assert app.activity_open
    assert not app.install_summary.winfo_manager()


@WINDOWS_GUI
def test_error_and_cancel_keep_progress_and_new_attempt_resets_it(app):
    app._begin_setup_progress()
    app.events.put(('progress', 'compile', 'Building Halo.', 50))
    _drain_events(app)
    held = float(app.progress['value'])
    app._cancel_setup()
    app.events.put(('progress', 'compile', 'Late queued build report.', 100))
    app.events.put(('error', 'Setup cancelled. Existing saves were kept.'))
    app.events.put(('idle',))
    _drain_events(app)
    assert float(app.progress['value']) == held
    assert str(app.progress.cget('mode')) == 'determinate'
    app._begin_setup_progress()
    assert float(app.progress['value']) == 0
    assert app.progress_label.get() == '0%'


@WINDOWS_GUI
def test_box_art_pending_stays_at_99_with_retry_action(app):
    from halo_frame_installer.install import InstallResult
    result = InstallResult('/home/steamos/Games/HaloCENativeVR', False,
        {'status': 'added', 'artwork': {'status': 'manual',
         'reason': 'Steam artwork directory is busy.'}}, None)
    app.events.put(('complete', result))
    app.events.put(('idle',))
    _drain_events(app)
    assert float(app.progress['value']) == 99
    assert 'Steam info pending' in app.phase.get()
    assert not _disabled(app.retry_button)


@WINDOWS_GUI
def test_disconnect_phase_does_not_finish_before_the_installer_result(app):
    from halo_frame_installer.install import InstallResult
    app.events.put(('progress', 'disconnect', 'Closing the setup SSH connection.', None))
    _drain_events(app)
    assert float(app.progress['value']) == 99
    assert app.phase.get() == 'Closing the setup connection'
    app.events.put(('progress', 'disconnected', 'Setup has disconnected from your Frame.', None))
    _drain_events(app)
    assert float(app.progress['value']) == 99
    assert app.phase.get() == 'Disconnected from your Frame'
    result = InstallResult('/home/steamos/Games/HaloCENativeVR', False,
                           {'status': 'added'}, None)
    app.events.put(('complete', result))
    _drain_events(app)
    assert float(app.progress['value']) == 100


@WINDOWS_GUI
def test_detail_burst_is_retained_and_drain_yields_to_the_window(app):
    for index in range(250):
        app.events.put(('progress', 'detail', f'compile: task {index}', None))
    app._drain()
    assert not app.events.empty()  # One turn drains at most 100 events.
    while not app.events.empty():
        app._drain()
    assert app.log_lines == [f'compile: task {index}' for index in range(250)]
    assert float(app.progress['value']) == 0


@WINDOWS_GUI
def test_installer_worker_does_not_throttle_adjacent_build_details(app, monkeypatch):
    from halo_frame_installer import gui, install

    def fake_run(settings, maps_dir, progress, cancel):
        progress('compile', 'Compiling the native game.', 50)
        for index in range(250):
            progress('detail', f'compile: task {index}', None)
        return install.InstallResult('/home/steamos/Games/HaloCENativeVR', False,
                                     {'status': 'added'}, None)

    monkeypatch.setattr(install, 'run', fake_run)
    monkeypatch.setattr(gui.threading, 'Thread', _ImmediateThread)
    app.authorized.set(True)
    app.steam_closed.set(True)
    app.password.set('offline-secret')
    app._install(repair=True)
    while not app.events.empty():
        app._drain()
    assert [line for line in app.log_lines if line.startswith('compile: task ')] == [
        f'compile: task {index}' for index in range(250)]
    assert float(app.progress['value']) == 100
    assert not app.password.get()


@WINDOWS_GUI
def test_library_retry_resets_the_progress_before_starting_worker(app, monkeypatch):
    from halo_frame_installer import gui

    class HoldingThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(gui.threading, 'Thread', HoldingThread)
    app.progress_state.finish(pending=True)
    app._display_progress()
    app.steam_closed.set(True)
    app.password.set('offline-secret')
    app._retry_steam()
    assert float(app.progress['value']) == 0
    assert app.progress_label.get() == '0%'
    assert app.activity_open and app.busy


@WINDOWS_GUI
def test_minimum_window_keeps_running_progress_and_scrollable_activity_visible(app):
    width, height = app.minsize()
    app.geometry(f'{width}x{height}')
    app.deiconify()
    app.installing = True
    app._show_page(2)
    app._begin_setup_progress()
    app._set_busy(True)
    app.update()
    for control in (app.progress, app.phase_label, app.log, app.activity_scrollbar, app.cancel_button):
        assert control.winfo_ismapped()
        left = control.winfo_rootx() - app.winfo_rootx()
        top = control.winfo_rooty() - app.winfo_rooty()
        assert left >= 0 and top >= 0
        assert left + control.winfo_width() <= app.winfo_width()
        assert top + control.winfo_height() <= app.winfo_height()


@WINDOWS_GUI
def test_uninstall_navigation_needs_ssh_but_no_iso_or_game_data_authorization(app):
    app.mode.set('uninstall')
    assert app.keep_saves.get()
    assert not app.source.get() and not app.authorized.get()
    assert app.uninstall_card.winfo_manager()
    assert not app.data_panel.winfo_manager() and not app.data_consent.winfo_manager()
    app._continue()
    assert app.current_page == 1
    app._continue()
    assert app.current_page == 1  # An SSH password is still required.
    app.password.set('offline-secret')
    app._continue()
    assert app.current_page == 1  # Closing games is still required.
    app.steam_closed.set(True)
    app._continue()
    assert app.current_page == 2
    assert app.primary_button.cget('text') == 'Uninstall Halo VR'
    assert app.summary_source.get() == '~/Games/HaloCENativeVR'
    assert 'backup' in app.summary_action.get()
    app.keep_saves.set(False)
    assert 'Remove saves' in app.summary_action.get()
    app.mode.set('install')
    app._show_page(0)
    app._continue()
    assert app.current_page == 0  # The install data/authorization gate returns.
    assert app.data_panel.winfo_manager() and app.data_consent.winfo_manager()
    assert not app.uninstall_card.winfo_manager()


@WINDOWS_GUI
@pytest.mark.parametrize('keep_saves', [True, False])
def test_uninstall_worker_uses_no_game_data_and_clears_credentials(app, monkeypatch, keep_saves):
    from halo_frame_installer import gui, install
    calls = []
    confirmations = []

    def fake_uninstall(self, settings, progress, cancel, *, keep_saves):
        calls.append((settings, settings.password, keep_saves))
        progress('uninstall', 'Removing native Halo.', 50)
        progress('disconnect', 'Closing the setup SSH connection.', None)
        progress('disconnected', 'Setup has disconnected from your Frame.', None)
        return install.UninstallResult('/home/steamos/Games/HaloCENativeVR', True, False,
            '/home/steamos/Games/HaloCENativeVR-saves-offline' if keep_saves else None,
            {'status': 'removed'}, None)

    monkeypatch.setattr(install.Installer, 'uninstall', fake_uninstall)
    monkeypatch.setattr(gui.threading, 'Thread', _ImmediateThread)
    monkeypatch.setattr(gui.messagebox, 'askyesno',
                        lambda title, message, **kwargs: confirmations.append(message) or True)
    for name in ('inspect_image', 'inspect_maps', 'extract_image', 'copy_maps'):
        monkeypatch.setattr(gui, name, lambda *args, **kwargs: pytest.fail('Uninstall accessed game data.'))
    monkeypatch.setattr(app.music, 'load', lambda *args: pytest.fail('Uninstall loaded game music.'))
    app.mode.set('uninstall')
    app.keep_saves.set(keep_saves)
    app.steam_closed.set(True)
    app.password.set('offline-secret')
    app._uninstall()
    _drain_events(app)
    settings, password, saved = calls[0]
    assert password == 'offline-secret' and saved is keep_saves
    assert settings.close_steam_for_shortcut is False
    assert not settings.password and not app.password.get()
    assert len(confirmations) == 1
    assert '~/Games/HaloCENativeVR' in confirmations[0] and 'Steam library entry' in confirmations[0]
    assert ('backed up' if keep_saves else 'will also be removed') in confirmations[0]
    assert float(app.progress['value']) == 100
    assert app.phase.get() == 'Halo VR uninstalled'
    assert app.last_result is None and not app.retry_button.winfo_manager()
    assert not app.busy and not app.uninstall_committing
    assert app._test_dialogs[-1][0] == 'Uninstall complete'
    assert 'Open Steam and launch' not in app.status.get()
    assert ('Campaign save backup:' in app.status.get()) is keep_saves


@WINDOWS_GUI
def test_uninstall_confirmation_can_decline_without_starting_worker(app, monkeypatch):
    from halo_frame_installer import gui, install
    monkeypatch.setattr(gui.messagebox, 'askyesno', lambda *args, **kwargs: False)
    monkeypatch.setattr(install.Installer, 'uninstall', lambda *args, **kwargs: pytest.fail('Uninstall was not confirmed.'))
    app.mode.set('uninstall')
    app.steam_closed.set(True)
    app.password.set('offline-secret')
    app._uninstall()
    assert not app.busy and not app.installing
    assert not any(event[0] in ('progress', 'uninstall_complete', 'error')
                   for event in list(app.events.queue))


@WINDOWS_GUI
def test_missing_native_game_has_an_idempotent_uninstall_message(app):
    from halo_frame_installer.install import UninstallResult
    result = UninstallResult('/home/steamos/Games/HaloCENativeVR', False, True,
                             None, {'status': 'already-absent'}, None)
    app.events.put(('uninstall_complete', result))
    _drain_events(app)
    assert float(app.progress['value']) == 100
    assert 'already absent' in app.status.get()
    assert 'launch' not in app.status.get().lower()


@WINDOWS_GUI
def test_uninstall_can_cancel_before_removal_but_not_during_commit(app, monkeypatch):
    from halo_frame_installer import gui
    app.mode.set('uninstall')
    app.operation = 'uninstall'
    app.installing = True
    app._set_busy(True)
    app._cancel_setup()
    assert app.cancel.is_set()
    app.cancel.clear()
    app.events.put(('progress', 'uninstall', 'Finishing the removal transaction.', None))
    _drain_events(app)
    assert app.uninstall_committing and _disabled(app.cancel_button)
    monkeypatch.setattr(gui.messagebox, 'askyesno', lambda *args, **kwargs: pytest.fail('Removal cannot be interrupted.'))
    app._cancel_setup()
    app._close()
    assert not app.cancel.is_set()
    assert 'Finishing removal' in app.status.get()
    app.events.put(('idle',))
    _drain_events(app)
    assert not app.uninstall_committing and not app.busy


@WINDOWS_GUI
def test_uninstall_choices_and_active_layout_fit_minimum_window(app):
    app.geometry('900x620')
    app.deiconify()
    app.mode.set('uninstall')
    app._show_page(0)
    app.update()
    uninstall_choice = app.mode_choices[-1]
    assert uninstall_choice.value == 'uninstall' and uninstall_choice.winfo_ismapped()
    for control in (uninstall_choice, app.primary_button):
        left = control.winfo_rootx() - app.winfo_rootx()
        top = control.winfo_rooty() - app.winfo_rooty()
        assert left >= 0 and top >= 0
        assert left + control.winfo_width() <= app.winfo_width()
        assert top + control.winfo_height() <= app.winfo_height()


@WINDOWS_GUI
def test_menu_music_is_enabled_without_a_stop_or_mute_button(app):
    assert not app.music.muted
    assert not hasattr(app, 'music_button') and not hasattr(app, '_toggle_music')
    visible = '\n'.join(_display_text(app))
    assert 'Music: OFF' not in visible and 'Stop music' not in visible


@WINDOWS_GUI
def test_default_window_shows_all_operations_and_game_data_authorization(app):
    app.geometry('1040x720')
    app.deiconify()
    app._show_page(0)
    app.update()
    canvas = app.pages[0].canvas
    top = canvas.winfo_rooty()
    bottom = top + canvas.winfo_height()
    for control in (*app.mode_choices, app.data_authorization):
        assert control.winfo_ismapped()
        assert top <= control.winfo_rooty()
        assert control.winfo_rooty() + control.winfo_height() <= bottom
    assert len({control.winfo_rooty() for control in app.mode_choices}) == 1
    assert 'uninstall' in app.page_subtitle.cget('text').lower()


@WINDOWS_GUI
def test_revision_guidance_names_validated_rev_2_and_checked_cache_builds(app):
    import tkinter as tk
    assert 'USA Rev 2 validated' in app.asset_status.get()
    assert 'checked automatically' in app.asset_status.get()
    app._show_help()
    dialogs = [widget for widget in app.winfo_children() if isinstance(widget, tk.Toplevel)]
    try:
        assert len(dialogs) == 1
        text = '\n'.join(_display_text(dialogs[0]))
        for build in ('01.10.12.2276', '01.08.15.1749', '01.01.14.2342'):
            assert build in text
        assert 'NTSC:' in text and 'PAL:' in text
        assert 'PC and Xbox 360 data are not supported' in text
    finally:
        for dialog in dialogs:
            dialog.destroy()


@WINDOWS_GUI
@pytest.mark.parametrize('mode', ['install', 'repair', 'library', 'uninstall'])
@pytest.mark.parametrize('games_closed', [False, True])
def test_game_closed_acknowledgment_never_authorizes_steam_shutdown(app, mode, games_closed):
    app.mode.set(mode)
    app.steam_closed.set(games_closed)
    app.password.set('offline-secret')
    assert app._settings().close_steam_for_shortcut is False
    assert 'Steam Home and SteamVR stay running' in app.connection_steam_note.cget('text')


@WINDOWS_GUI
@pytest.mark.parametrize('operation', ['continue', 'install', 'retry', 'uninstall'])
def test_closed_game_gate_only_requests_closing_games(app, operation):
    app.password.set('offline-secret')
    app.authorized.set(True)
    app.steam_closed.set(False)
    if operation == 'continue':
        app._show_page(1)
        app._continue()
    elif operation == 'install':
        app._install(repair=True)
    elif operation == 'retry':
        app._retry_steam()
    else:
        app.mode.set('uninstall')
        app._uninstall()
    message = app._test_dialogs[-1][1]
    assert 'Save and close running games' in message
    assert 'Keep Steam Home and SteamVR running' in message
    assert 'restart Steam' not in message and 'Quit Steam' not in message
    assert not app.busy


@WINDOWS_GUI
@pytest.mark.parametrize('kind', ['add', 'artwork', 'remove'])
def test_manual_library_fallback_uses_steam_ui_without_teardown_instructions(app, kind):
    from halo_frame_installer.install import InstallResult, UninstallResult
    game = '/home/steamos/Games/HaloCENativeVR'
    if kind == 'remove':
        result = UninstallResult(game, False, False, None,
                                 {'status': 'manual', 'reason': 'Steam is active.'}, None)
        event = 'uninstall_complete'
        expected = 'Remove Non-Steam Game'
    else:
        steam = ({'status': 'manual', 'reason': 'Steam is active.'} if kind == 'add' else
                 {'status': 'added', 'artwork': {'status': 'manual', 'reason': 'Artwork is pending.'}})
        result = InstallResult(game, False, steam, None)
        event = 'complete'
        expected = 'Add a Non-Steam Game' if kind == 'add' else 'custom artwork'
    app.events.put((event, result))
    _drain_events(app)
    assert float(app.progress['value']) == 99
    assert expected in app.status.get()
    assert 'Quit Steam' not in app.status.get() and 'restart Steam' not in app.status.get()


@WINDOWS_GUI
def test_steam_info_navigation_requires_connection_but_no_iso_or_authorization(app):
    app.mode.set('library')
    assert app.library_card.winfo_manager()
    assert not app.data_panel.winfo_manager() and not app.data_consent.winfo_manager()
    assert not app.uninstall_card.winfo_manager()
    assert 'No ISO or rebuild' in '\n'.join(_display_text(app.library_card))
    app._continue()
    assert app.current_page == 1
    app._continue()
    assert app.current_page == 1
    app.password.set('offline-secret')
    app._continue()
    assert app.current_page == 1  # Existing game-close acknowledgement remains required.
    app.steam_closed.set(True)
    app._continue()
    assert app.current_page == 2
    assert app.primary_button.cget('text') == 'Update Steam info'
    assert app.summary_source.get() == '~/Games/HaloCENativeVR'
    assert 'Steam Notes' in app.summary_action.get()
    assert 'custom artwork and notes are preserved' in app.summary_note.get()
    app.mode.set('install')
    app._show_page(0)
    app._continue()
    assert app.current_page == 0
    assert not app.library_card.winfo_manager()
    assert app.data_panel.winfo_manager() and app.data_consent.winfo_manager()


@WINDOWS_GUI
@pytest.mark.parametrize('transport', ['network', 'usb'])
def test_steam_info_worker_does_not_read_game_data_or_build_and_clears_credentials(app, monkeypatch, transport):
    from halo_frame_installer import gui, install
    calls = []

    def fake_library(self, settings, progress, cancel):
        calls.append((settings, settings.password))
        assert settings.transport == transport
        assert not settings.close_steam_for_shortcut
        progress('steam', 'Updating library info.', 100)
        progress('disconnected', 'Setup has disconnected from your Frame.', None)
        return install.InstallResult('/home/steamos/Games/HaloCENativeVR', False,
            {'status': 'added', 'artwork': {'status': 'added', 'icon': {'status': 'added'}},
             'notes': {'status': 'added', 'title': 'About Halo', 'content': 'Campaign and controls.', 'message': 'Added.'}}, None)

    monkeypatch.setattr(install.Installer, 'add_to_steam', fake_library)
    monkeypatch.setattr(install, 'run', lambda *args, **kwargs: pytest.fail('Steam info rebuilt the game.'))
    monkeypatch.setattr(gui.threading, 'Thread', _ImmediateThread)
    for name in ('inspect_image', 'inspect_maps', 'extract_image', 'copy_maps'):
        monkeypatch.setattr(gui, name, lambda *args, **kwargs: pytest.fail('Steam info accessed game data.'))
    monkeypatch.setattr(app.music, 'load', lambda *args: pytest.fail('Steam info read game music.'))
    app.mode.set('library')
    app.transport.set(transport)
    app.steam_closed.set(True)
    app.password.set('offline-secret')
    app._show_page(2)
    app._continue()
    _drain_events(app)
    assert len(calls) == 1
    settings, password = calls[0]
    assert password == 'offline-secret'
    assert not settings.password and not app.password.get()
    assert not app.busy and not app.installing
    assert float(app.progress['value']) == 100
    assert app.phase.get() == 'Steam info updated'
    assert 'native game and saves were kept' in app.status.get()
    assert 'installed.' not in app.status.get()
    assert app._test_dialogs[-1][0] == 'Steam info updated'


@WINDOWS_GUI
@pytest.mark.parametrize('pending', ['icon', 'notes', 'artwork'])
def test_steam_info_partial_results_stay_actionable_without_claiming_complete_update(app, pending):
    from halo_frame_installer.install import InstallResult
    app.mode.set('library')
    app.operation = 'library'
    app.password_to_redact = 'offline-secret'
    steam = {'status': 'added', 'artwork': {'status': 'added', 'icon': {'status': 'added'}},
             'notes': {'status': 'added', 'title': 'About Halo', 'content': 'Campaign and controls.'}}
    if pending == 'icon':
        steam['artwork']['icon'] = {'status': 'manual', 'reason': 'Icon not persisted. offline-secret'}
    elif pending == 'notes':
        steam['notes'].update(status='manual', message='Open Steam Notes. offline-secret')
    else:
        steam['artwork']['status'] = 'manual'
        steam['artwork']['reason'] = 'Banner unavailable. offline-secret'
    app.events.put(('complete', InstallResult('/home/steamos/Games/HaloCENativeVR', False, steam, None)))
    app.events.put(('idle',))
    _drain_events(app)
    assert float(app.progress['value']) == 99
    assert app.phase.get() == 'Ready to play · Steam info pending'
    assert 'some Steam library info needs one more step' in app.status.get()
    assert 'has been updated' not in app.status.get()
    assert not _disabled(app.retry_button)
    assert 'offline-secret' not in app.status.get()
    assert 'offline-secret' not in '\n'.join(app.log_lines)
    assert app._test_dialogs[-1][0] == 'Steam info needs attention'
    assert bool(app.notes_button.winfo_manager()) is (pending == 'notes')


@WINDOWS_GUI
def test_manual_steam_description_is_copyable_and_never_overrides_about_game(app):
    import tkinter as tk
    from halo_frame_installer.gui import Button
    from halo_frame_installer.install import InstallResult
    app.operation = 'library'
    app.password_to_redact = 'offline-secret'
    app.events.put(('complete', InstallResult('/home/steamos/Games/HaloCENativeVR', False,
        {'status': 'added', 'notes': {'status': 'manual', 'title': 'Halo CE VR — About & controls',
         'content': 'Explore Halo.\nA: Jump. B: Melee. offline-secret', 'message': 'Steam Notes needs a manual step.'}}, None)))
    app.events.put(('clear_password',))
    app.events.put(('idle',))
    _drain_events(app)
    assert app.notes_button.winfo_manager() and not _disabled(app.notes_button)
    assert 'description in Steam Notes' in app.status.get()
    app._show_steam_note()
    dialogs = [widget for widget in app.winfo_children() if isinstance(widget, tk.Toplevel)]
    try:
        assert len(dialogs) == 1
        visible = '\n'.join(_display_text(dialogs[0]))
        assert 'Add this description in Steam Notes' in visible
        assert 'About this game' not in visible
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        fields = [widget for widget in descendants(dialogs[0]) if isinstance(widget, tk.Text)]
        assert len(fields) == 1
        assert fields[0].get('1.0', 'end-1c') == 'Explore Halo.\nA: Jump. B: Melee. [redacted]'
        copy = next(widget for widget in descendants(dialogs[0])
                    if isinstance(widget, Button) and widget.cget('text') == 'Copy description')
        copy.invoke()
        assert app.clipboard_get() == 'Explore Halo.\nA: Jump. B: Melee. [redacted]'
        app.clipboard_clear()
    finally:
        for dialog in dialogs:
            dialog.destroy()


@WINDOWS_GUI
@pytest.mark.parametrize('icon_status', ['existing', 'custom', 'unchanged', 'preserved'])
def test_preserved_steam_info_is_successful_without_manual_pending(app, icon_status):
    from halo_frame_installer.install import InstallResult
    app.operation = 'library'
    app.events.put(('complete', InstallResult('/home/steamos/Games/HaloCENativeVR', False,
        {'status': 'added', 'artwork': {'status': 'unchanged', 'icon': {'status': icon_status}},
         'notes': {'status': 'custom', 'title': 'Halo CE VR — About & controls', 'content': 'Player notes.'}}, None)))
    app.events.put(('idle',))
    _drain_events(app)
    assert float(app.progress['value']) == 100
    assert app.phase.get() == 'Steam info updated'
    assert 'existing custom game note was kept' in app.status.get()
    assert not app.notes_button.winfo_manager()


@WINDOWS_GUI
def test_all_operation_tile_captions_fit_minimum_width(app):
    app.geometry('900x620')
    app.deiconify()
    app._show_page(0)
    app.update()
    assert {choice.value for choice in app.mode_choices} == {'install', 'repair', 'library', 'uninstall'}
    for choice in app.mode_choices:
        for item in choice.find_all():
            if choice.type(item) == 'text':
                left, top, right, bottom = choice.bbox(item)
                assert 0 <= left < right <= choice.winfo_width()
                assert 0 <= top < bottom <= choice.winfo_height()
