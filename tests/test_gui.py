import sys
from pathlib import Path
import pytest

def test_control_guide_matches_expected_layout():
    from halo_frame_installer.gui import CONTROLS
    for action in ('Jump', 'Melee', 'Reload / use', 'Change weapon',
                   'LB  Change grenade', 'RB  Flashlight', 'Both grips  Recenter'):
        assert action in CONTROLS

@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Tk packaging smoke test')
def test_gui_offline_smoke():
    from halo_frame_installer.selftest import smoke_test
    result = smoke_test(Path(__file__).resolve().parents[1] / 'resources')
    assert result['ok'] and result['guiInitialized']
    assert result['networkConnections'] == 0
