import json
import threading
from pathlib import Path

import pytest

from halo_frame_installer.install import Installer
from halo_frame_installer.ssh import CancelledError, Settings, SSHError

RESOURCES = Path(__file__).resolve().parents[1] / 'resources'
GAME = '/home/steamos/Games/HaloCENativeVR'


class UninstallConnection:
    def __init__(self, settings, *, manual=False, already_absent=False):
        self.settings = settings
        self.closed = False
        self.connected = False
        self.commands = []
        self.uploads = []
        self.manual = manual
        self.already_absent = already_absent
        self.host_fingerprint = 'SHA256:public'
        self.removed = False

    def connect(self):
        self.connected = True

    def close(self):
        self.closed = True

    def put(self, local, remote, **kwargs):
        self.uploads.append((Path(local).name, remote))

    def run(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        if argv[1] == '-c':
            assert argv[-1] == 'preflight-uninstall'
            data = {'home': '/home/steamos', 'cachePath': '/home/steamos/.cache/halo-frame-installer',
                    'gamePath': GAME, 'uninstallSupported': True}
        else:
            assert argv[2] == 'uninstall'
            assert 'cancel_event' not in kwargs
            assert 'Removal may be incomplete' in kwargs['timeout_message']
            run_id = argv[argv.index('--run-id') + 1]
            if self.manual:
                data = {'gamePath': GAME, 'uninstalled': False, 'savedBackupPath': None,
                        'steam': {'status': 'manual', 'reason': 'Steam removal could not be verified; the game was kept.',
                                  'instructions': 'Remove the native shortcut using Steam library controls, then retry Uninstall Halo VR.'}}
            else:
                self.removed = not self.already_absent
                data = {'gamePath': GAME, 'uninstalled': self.removed, 'alreadyAbsent': self.already_absent,
                        'savedBackupPath': '/home/steamos/Games/HaloCENativeVR-saves-' + run_id
                            if '--keep-saves' in argv and self.removed else None,
                        'steam': {'status': 'already-absent' if self.already_absent else 'removed'}}
        return 'HFI_RESULT ' + json.dumps(data)


def test_uninstall_needs_no_iso_maps_or_build_and_disconnects_before_success():
    fake = UninstallConnection(Settings('frame', 'private', close_steam_for_shortcut=True))
    stages = []
    def progress(stage, message, percent=None):
        stages.append(stage)
        if stage in ('complete', 'disconnected'):
            assert fake.closed
    result = Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings, progress)
    assert result.uninstalled and not result.requires_manual_steam_step
    assert result.saved_backup_path.startswith('/home/steamos/Games/HaloCENativeVR-saves-')
    assert [name for name, remote in fake.uploads] == ['frame_storage.py', 'remote_install.py', 'steam_shortcut.py', 'steam_live.py']
    assert len(fake.commands) == 2
    assert '--keep-saves' in fake.commands[-1][0] and '--close-steam' not in fake.commands[-1][0]
    assert stages[-3:] == ['disconnect', 'disconnected', 'complete']


def test_user_can_explicitly_remove_contained_campaign_saves():
    fake = UninstallConnection(Settings('frame', 'private'))
    result = Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings, keep_saves=False)
    assert result.uninstalled and result.saved_backup_path is None
    assert '--keep-saves' not in fake.commands[-1][0]


def test_uninstall_is_idempotent_when_the_game_and_entry_are_absent():
    fake = UninstallConnection(Settings('frame', 'private'), already_absent=True)
    result = Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings)
    assert result.already_absent and not result.uninstalled and fake.closed


def test_manual_steam_step_is_an_actionable_failure_and_never_says_uninstalled():
    fake = UninstallConnection(Settings('frame', 'private'), manual=True)
    stages = []
    with pytest.raises(SSHError, match='game was kept') as error:
        Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings,
            lambda stage, message, percent=None: stages.append(stage))
    assert 'retry Uninstall Halo VR' in str(error.value)
    assert 'complete' not in stages and not fake.removed and fake.closed


def test_cancel_before_uninstall_connects_to_nothing():
    cancel = threading.Event()
    cancel.set()
    fake = UninstallConnection(Settings('frame', 'private'))
    with pytest.raises(CancelledError, match='before removal'):
        Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings, cancel_event=cancel)
    assert not fake.connected and not fake.commands and not fake.uploads and fake.closed


def test_cancel_during_helper_upload_never_starts_removal():
    cancel = threading.Event()
    fake = UninstallConnection(Settings('frame', 'private'))
    original = fake.put
    def put(*args, **kwargs):
        original(*args, **kwargs)
        cancel.set()
    fake.put = put
    with pytest.raises(CancelledError, match='before removal'):
        Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings, cancel_event=cancel)
    assert len(fake.commands) == 1 and not fake.removed and fake.closed


def test_late_cancel_cannot_abandon_an_uninstall_that_has_started():
    cancel = threading.Event()
    fake = UninstallConnection(Settings('frame', 'private'))
    original = fake.run
    def run(argv, **kwargs):
        if argv[1] != '-c':
            cancel.set()
        return original(argv, **kwargs)
    fake.run = run
    result = Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings, cancel_event=cancel)
    assert result.uninstalled and fake.removed and fake.closed


def test_post_removal_bookkeeping_warning_is_visible_without_false_failure():
    fake = UninstallConnection(Settings('frame', 'private'))
    original = fake.run
    warning = 'Halo was removed, but the installer operation record could not be updated.'
    def run(argv, **kwargs):
        response = original(argv, **kwargs)
        if argv[1] != '-c':
            data = json.loads(response.split(' ', 1)[1])
            data['warning'] = warning
            response = 'HFI_RESULT ' + json.dumps(data)
        return response
    fake.run = run
    events = []
    result = Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings,
        lambda *event: events.append(event))
    assert result.uninstalled and fake.closed
    assert ('detail', warning, None) in events
    assert events[-1][0] == 'complete'


def host_response(fake, **extra):
    original = fake.run
    def run(argv, **kwargs):
        response = original(argv, **kwargs)
        if argv[1] != '-c':
            data = json.loads(response.split(' ', 1)[1])
            data.update(extra)
            response = 'HFI_RESULT ' + json.dumps(data)
        return response
    fake.run = run


def test_successful_uninstall_retains_its_result_when_usb_cleanup_needs_attention():
    class CleanupFailure(UninstallConnection):
        def close(self):
            self.closed = True
            raise SSHError('Temporary USB forward cleanup failed private')
    fake = CleanupFailure(Settings('', 'private', transport='usb'))
    events = []
    result = Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings,
        lambda *event: events.append(event))
    assert result.uninstalled and result.saved_backup_path
    assert result.connection_cleanup_pending and 'Unplug the USB cable' in result.cleanup_warning
    assert 'private' not in result.cleanup_warning
    assert not any(event[0] in ('disconnected', 'complete') for event in events)
    assert events[-1][0] == 'cleanup-pending' and events[-1][2] == 99


def test_uncertain_uninstall_retains_history_without_claiming_removed_or_already_absent():
    fake = UninstallConnection(Settings('frame', 'private'))
    previous_save = '/home/steamos/Games/HaloCENativeVR-saves-' + 'a' * 32
    retained = '/home/steamos/Games/.HaloCENativeVR-uninstall-unsafe-manual-folder'
    warning = 'An unsafe uninstall folder was preserved; inspect it before retrying.'
    host_response(fake, uninstalled=False, alreadyAbsent=False, savedBackupPath=None,
                  removalPending=True, warning=warning,
                  retainedQuarantinePaths=[retained], recoveredSaveBackupPaths=[previous_save])
    events = []
    result = Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings,
        lambda *event: events.append(event))
    assert result.removal_pending and not result.uninstalled and not result.already_absent
    assert result.removal_warning == warning
    assert result.retained_quarantine_paths == (retained,)
    assert result.recovered_save_backup_paths == (previous_save,)
    assert result.saved_backup_path is None
    assert not any(event[0] == 'complete' for event in events)
    assert events[-1][0] == 'removal-pending' and events[-1][2] == 99


def test_manual_steam_failure_preserves_recovered_save_history_and_warning():
    fake = UninstallConnection(Settings('frame', 'private'), manual=True)
    backup = '/home/steamos/Games/HaloCENativeVR-saves-' + 'b' * 32
    warning = 'Recovered saves from an interrupted uninstall.'
    host_response(fake, warning=warning, recoveredSaveBackupPaths=[backup])
    events = []
    with pytest.raises(SSHError, match='game was kept') as error:
        Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings,
            lambda *event: events.append(event))
    assert warning in str(error.value) and backup in str(error.value)
    assert ('detail', 'Recovered campaign save backup: ' + backup, None) in events
    assert not any(event[0] == 'complete' for event in events)


@pytest.mark.parametrize('extra', [
    {'recoveredSaveBackupPaths': ['/home/other/Games/HaloCENativeVR-saves-' + 'a' * 32]},
    {'recoveredSaveBackupPaths': ['/home/steamos/Games/HaloCENativeVR-saves-not-a-run']},
    {'retainedQuarantinePaths': ['/home/steamos/Games/.HaloCENativeVR-uninstall-../other']},
    {'retainedQuarantinePaths': ['/home/steamos/Games/.HaloCENativeVR-uninstall-bad\\other']},
    {'retainedQuarantinePaths': ['/home/steamos/Games/.HaloCENativeVR-uninstall-bad\nother']},
    {'retainedQuarantinePaths': ['/home/steamos/Games/.HaloCENativeVR-uninstall-' + 'a' * 256]},
    {'recoveredSaveBackupPaths': ['/home/steamos/Games/HaloCENativeVR-saves-' + 'a' * 32] * 2},
    {'retainedQuarantinePaths': ['folder'] * 65},
    {'warning': 'x' * 4097},
    {'removalPending': 'true'},
    {'removalPending': True, 'uninstalled': True},
    {'retainedQuarantinePaths': ['/home/steamos/Games/.HaloCENativeVR-uninstall-' + 'a' * 32]},
])
def test_invalid_uninstall_recovery_history_never_reports_success(extra):
    fake = UninstallConnection(Settings('frame', 'private'))
    host_response(fake, **extra)
    stages = []
    with pytest.raises(SSHError, match='invalid uninstall'):
        Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings,
            lambda stage, message, percent=None: stages.append(stage))
    assert 'complete' not in stages and fake.closed


def test_pending_overflow_can_be_reported_without_a_retained_path_list():
    fake = UninstallConnection(Settings('frame', 'private'))
    host_response(fake, uninstalled=False, alreadyAbsent=False, savedBackupPath=None,
                  removalPending=True, warning='Too many interrupted uninstall folders; retry cleanup.')
    result = Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings)
    assert result.removal_pending and result.retained_quarantine_paths == ()


def test_uninstall_failure_is_not_masked_by_disconnect_failure():
    fake = UninstallConnection(Settings('frame', 'private'), manual=True)
    fake.close = lambda: (_ for _ in ()).throw(EOFError('private'))
    with pytest.raises(SSHError, match='game was kept') as error:
        Installer(lambda settings: fake, RESOURCES).uninstall(fake.settings)
    assert 'private' not in str(error.value)
