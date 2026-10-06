"""Offline source-integration regressions; no game data or headset connection."""
import ast
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("experimental_engine_check", ROOT / "scripts/check-experimental-engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


TWO_PASS = """
static void bind_textures(struct nv2a_pixel_shader_key *key, float texture_scale[4][4])
{
    GLenum gl_targets[D3DTSS_MAXSTAGES];
    GLuint gl_textures[D3DTSS_MAXSTAGES];
    int stage;
    for (stage = 0; stage < D3DTSS_MAXSTAGES; stage++)
    {
        gl_textures[stage] = xgpu_texture_get(texture, palette, &gl_targets[stage], &description);
    }
    for (stage = 0; stage < D3DTSS_MAXSTAGES; stage++)
        state_texture(stage, gl_targets[stage], gl_textures[stage]);
}
"""


def literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("Missing " + name + " in " + str(path))


def test_installer_and_remote_metadata_share_the_exact_experimental_engine_pin():
    for path, name in ((ROOT / "src/halo_frame_installer/install.py", "SOURCE_COMMIT"),
                       (ROOT / "resources/remote_install.py", "SOURCE_COMMIT"),
                       (ROOT / "resources/steam_shortcut.py", "ICON_SOURCE_COMMIT")):
        assert literal_assignment(path, name) == engine.SOURCE_COMMIT


def test_two_pass_texture_binding_is_accepted():
    engine.check_texture_binding(TWO_PASS)


@pytest.mark.parametrize("broken", [
    TWO_PASS.replace("gl_textures[stage] = xgpu_texture_get", "state_texture(stage, gl_targets[stage], gl_textures[stage]); gl_textures[stage] = xgpu_texture_get"),
    TWO_PASS.replace("for (stage = 0; stage < D3DTSS_MAXSTAGES; stage++)\n        state_texture", "state_texture"),
    TWO_PASS.replace("state_texture(stage, gl_targets[stage], gl_textures[stage])", "state_texture(stage, GL_TEXTURE_2D, 0)"),
])
def test_shader_upload_binding_regressions_are_rejected(broken):
    with pytest.raises(engine.EngineCheckError, match="Texture binding|Final texture bindings"):
        engine.check_texture_binding(broken)


@pytest.mark.parametrize("path", ["../outside.c", "/outside.c", "source/network/network_messages.c", "resources/remote_install.py"])
def test_engine_patch_cannot_hide_unreviewed_paths(path):
    with pytest.raises(engine.EngineCheckError, match="outside the reviewed"):
        engine.patch_files("diff --git a/" + path + " b/" + path + "\n")


def test_patch_path_allowlist_contains_both_new_header_and_existing_input_hooks():
    text = (ROOT / "resources/frame-controls.patch").read_text(encoding="utf-8")
    paths = engine.patch_files(text)
    assert {"port/linux/src/vr_locomotion.h", "port/linux/src/vr.c", "port/linux/src/port_config.c", "source/game/player_control.c"} <= paths


def test_protocol_11_engine_cannot_be_mislabeled_as_matching_experimental_coop(tmp_path):
    path = tmp_path / "port/linux/include/halo_port_limits.h"
    path.parent.mkdir(parents=True)
    path.write_text("#define HALO_PORT_NETWORK_VERSION 11\n")
    with pytest.raises(engine.EngineCheckError, match="protocol 17"):
        engine.check_upstream(tmp_path)


def test_public_release_documentation_names_the_single_installer_download():
    for name in ("README.md", "docs/SETUP.md", "docs/RELEASE_NOTES.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "1.4.0" in text and "Halo-Steam-Frame-Mod-Setup-1.4.0.exe" in text
        assert "has not been published" not in text and "local experimental preview" not in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/download/v1.4.0/Halo-Steam-Frame-Mod-Setup-1.4.0.exe" in readme
    notes = (ROOT / "docs/RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert "cannot load old checkpoints" in notes and "save-v1.4" in notes


def test_actual_exact_pinned_engine_and_shipped_patch_when_checkout_is_supplied():
    source = os.environ.get("HALO_EXPERIMENTAL_ENGINE_SOURCE")
    if not source:
        pytest.skip("Set HALO_EXPERIMENTAL_ENGINE_SOURCE for the local offline engine integration check")
    result = engine.check_source(Path(source))
    assert result["ok"] and result["protocolVersion"] == 17
    assert result["offlineArm64NinjaGraph"] and result["headDirectedMovementIntegration"]
    assert result["stereoSunGlowIntegration"] and result["vrInternetCampaignMenu"]
    assert result["boundedSunGlowStrength"]
    assert result["nominalProjectileReticleIntegration"]
    assert result["renderRateProjectilePreviewIntegration"]
    assert result["networkCampaignOnlyIntegration"]
    assert not result["arm64LinkedBuild"] and not result["hardwareValidated"]
