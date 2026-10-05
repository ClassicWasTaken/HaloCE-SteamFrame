import json

import pytest

from halo_frame_installer.install import parse_activity
from halo_frame_installer.ssh import SSHError


def test_real_compiler_count_is_forwarded_without_becoming_overall_percentage():
    line = 'HFI_PROGRESS ' + json.dumps({'stage': 'compile', 'message': 'Compiled 123 of 456 tasks', 'percent': 123 * 100 / 456})
    stage, message, percent = parse_activity(line)
    assert stage == 'compile' and message == 'Compiled 123 of 456 tasks'
    assert percent == pytest.approx(123 * 100 / 456)


def test_build_output_is_activity_only_and_cannot_drive_progress():
    line = 'HFI_LOG ' + json.dumps({'stage': 'sdl', 'message': '[27/83] Building SDL audio', 'percent': 100})
    assert parse_activity(line) == ('detail', 'sdl: [27/83] Building SDL audio', None)


def test_old_phase_only_protocol_remains_compatible():
    assert parse_activity('HFI_PROGRESS {"stage":"source","message":"Fetching source"}') == ('source', 'Fetching source', None)
    assert parse_activity('HFI_RESULT {"built":true}') is None
    assert parse_activity('other plain output') is None


@pytest.mark.parametrize('percent', [None, True, False, -1, 101, '50', [], {}, float('nan'), float('inf'), -float('inf'), 10**1000])
def test_unusable_count_holds_at_the_stage_without_stopping_installation(percent):
    assert parse_activity('HFI_PROGRESS ' + json.dumps({'stage': 'toolchain', 'message': 'Installing LLVM', 'percent': percent})) == ('toolchain', 'Installing LLVM', None)


@pytest.mark.parametrize('data', [None, [], {}, {'stage': 2, 'message': 'x'}, {'stage': '', 'message': 'x'}, {'stage': 'compile', 'message': []}, {'stage': 'x' * 65, 'message': 'x'}, {'stage': 'compile', 'message': 'x' * 4097}])
def test_invalid_activity_payload_has_a_readable_protocol_error(data):
    with pytest.raises(SSHError, match='invalid setup activity'):
        parse_activity('HFI_PROGRESS ' + json.dumps(data))


def test_malformed_activity_json_has_a_readable_protocol_error():
    with pytest.raises(SSHError, match='invalid setup activity'):
        parse_activity('HFI_LOG {broken')
