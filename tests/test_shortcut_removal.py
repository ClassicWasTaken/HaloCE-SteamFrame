"""Keep uninstall atomic when a native Steam record cannot be identified."""

from collections import OrderedDict

import pytest

from test_uninstall import RUN_ID, game_bytes, installation


def config_bytes(configs):
    return {
        str(path): path.read_bytes()
        for config in configs
        for path in config.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("invalid", ["missing", "string", "zero", "below-shortcut-range"])
@pytest.mark.parametrize("only_malformed", [False, True])
@pytest.mark.parametrize("quoted", [False, True])
def test_invalid_native_id_keeps_game_all_accounts_and_artwork(
        installation, invalid, only_malformed, quoted):
    remote, steam, configs, _, _ = installation
    executable = str(remote.GAME / "halo")
    if only_malformed:
        for config in configs:
            path = config / "shortcuts.vdf"
            root = steam.loads(path.read_bytes())
            del root["shortcuts"].value["1"]
            path.write_bytes(steam.dumps(root))

    # Put the malformed record in the second account so the first account's
    # otherwise valid removal is planned before validation must refuse it.
    path = configs[1] / "shortcuts.vdf"
    root = steam.loads(path.read_bytes())
    fields = OrderedDict([
        ("AppName", steam.Value(1, "Renamed native Halo")),
        ("Exe", steam.Value(1, f'"{executable}"' if quoted else executable)),
    ])
    if invalid != "missing":
        kind, value = {
            "string": (1, "not-a-number"),
            "zero": (2, 0),
            "below-shortcut-range": (2, 0x7FFFFFFF),
        }[invalid]
        fields["appid"] = steam.Value(kind, value)
    root["shortcuts"].value["3"] = steam.Value(0, fields)
    path.write_bytes(steam.dumps(root))
    before_game = game_bytes(remote)
    before_configs = config_bytes(configs)

    result = remote.uninstall(RUN_ID, keep_saves=True)

    assert not result["uninstalled"]
    assert result["steam"]["status"] == "manual"
    assert "invalid app ID" in result["steam"]["reason"]
    assert result["savedBackupPath"] is None
    assert game_bytes(remote) == before_game
    # This also proves no shortcut backups were published and no managed or
    # custom artwork was deleted before the second account failed validation.
    assert config_bytes(configs) == before_configs
    assert not list(remote.GAME.parent.glob("*HaloCENativeVR-saves-*"))
    assert not list(remote.GAME.parent.glob(".HaloCENativeVR-uninstall-*"))


@pytest.mark.parametrize("variant", ["leading-quote", "trailing-quote", "double-quotes", "suffix", "arguments"])
def test_nonexact_executable_is_preserved_even_with_bad_id_and_native_title(installation, variant):
    remote, steam, configs, appids, _ = installation
    executable = str(remote.GAME / "halo")
    candidate = {
        "leading-quote": '"' + executable,
        "trailing-quote": executable + '"',
        "double-quotes": '""' + executable + '""',
        "suffix": executable + "-backup",
        "arguments": executable + " --custom",
    }[variant]
    path = configs[0] / "shortcuts.vdf"
    root = steam.loads(path.read_bytes())
    unrelated = OrderedDict([
        ("appid", steam.Value(1, "not-a-number")),
        ("AppName", steam.Value(1, steam.NAME)),
        ("Exe", steam.Value(1, candidate)),
        ("unknown", steam.Value(7, b"KEEPTHIS")),
    ])
    root["shortcuts"].value["3"] = steam.Value(0, unrelated)
    path.write_bytes(steam.dumps(root))
    custom_art = (configs[1] / "grid" / f"{appids[1]}.png").read_bytes()
    foreign_art = (configs[0] / "grid/10p.jpg").read_bytes()

    result = remote.uninstall(RUN_ID)

    assert result["uninstalled"]
    assert result["steam"]["status"] == "removed"
    assert result["steam"]["accounts"] == ["10", "20"]
    remaining = steam.loads(path.read_bytes())["shortcuts"].value
    assert set(remaining) == {"0", "2", "3"}
    assert remaining["3"].value == unrelated
    assert (configs[1] / "grid" / f"{appids[1]}.png").read_bytes() == custom_art
    assert (configs[0] / "grid/10p.jpg").read_bytes() == foreign_art
