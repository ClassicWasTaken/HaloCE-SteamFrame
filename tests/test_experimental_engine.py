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


@pytest.fixture
def recipe_projection(tmp_path):
    declaration = "import argparse\np = argparse.ArgumentParser()\n"
    declaration += "\n".join("p.add_argument('" + option + "')" for option in ("--cc", "--ld", "--sdk"))
    for path in engine.PATCH_FILES:
        if path.startswith("tools/test_") and path.endswith(".py"):
            candidate = tmp_path / path
            candidate.parent.mkdir(exist_ok=True)
            candidate.write_text(declaration, encoding="utf-8")
    (tmp_path / "configure.py").write_text("# configure boundary\n", encoding="utf-8")
    return tmp_path


def test_native_recipe_checks_every_shipped_test_in_the_projection(recipe_projection):
    actual = engine.check_build_recipe(recipe_projection)
    expected = {path for path in engine.PATCH_FILES if path.startswith("tools/test_") and path.endswith(".py")}
    assert set(actual) == expected and len(actual) == len(expected)


@pytest.mark.parametrize("name", ["test_vr_scope.py", "test_vr_scope_render.py", "test_vr_scope_backend.py",
                                 "test_vr_scope_hud.py", "test_vr_scope_link.py"])
def test_recipe_rejects_each_removed_scope_command(recipe_projection, name):
    text = (ROOT / "resources/build-native.sh").read_text(encoding="utf-8")
    text = text.replace("python3 configure.py", "python3 tools/" + name + " --cc clang\npython3 configure.py")
    with pytest.raises(engine.EngineCheckError, match="does not match the shipped"):
        engine.check_build_recipe(recipe_projection, text)


def test_recipe_rejects_missing_actual_test_file(recipe_projection):
    (recipe_projection / "tools/test_vr_framebuffer.py").unlink()
    with pytest.raises(engine.EngineCheckError, match="missing script: tools/test_vr_framebuffer.py"):
        engine.check_build_recipe(recipe_projection)


@pytest.mark.parametrize("before,after,diagnostic", [
    ("--sdk /usr/include", "--missing-sdk /usr/include", "unsupported option"),
    ("python3 tools/test_vr_tracking.py --cc clang", "python3 tools/test_vr_tracking.py --cc clang\npython3 tools/test_vr_tracking.py --cc clang", "repeats a regression"),
    ("--release --vr --linux-arm64-cc clang", "--release --linux-arm64-cc clang", "release ARM64 VR target"),
    ("ninja -j4 linux_arm64", "ninja -j4 linux", "configured ARM64 target"),
    ("set -euo pipefail", "set -u", "stop on failed checks"),
])
def test_recipe_rejects_invalid_commands_and_failure_masking(recipe_projection, before, after, diagnostic):
    text = (ROOT / "resources/build-native.sh").read_text(encoding="utf-8")
    assert before in text
    with pytest.raises(engine.EngineCheckError, match=diagnostic):
        engine.check_build_recipe(recipe_projection, text.replace(before, after))


def test_recipe_accepts_and_checks_local_delegated_cli_options(recipe_projection):
    (recipe_projection / "tools/test_vr_flashlight.py").write_text(
        "import test_vr_projectile_reticle as reticle\nreticle.main()\n", encoding="utf-8")
    assert "tools/test_vr_flashlight.py" in engine.check_build_recipe(recipe_projection)
    (recipe_projection / "tools/test_vr_projectile_reticle.py").write_text("def main(): pass\n", encoding="utf-8")
    with pytest.raises(engine.EngineCheckError, match="unsupported option"):
        engine.check_build_recipe(recipe_projection)


def test_public_release_documentation_names_the_single_installer_download():
    for name in ("README.md", "docs/SETUP.md", "docs/RELEASE_NOTES.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "1.4.2" in text and "Halo-Steam-Frame-Mod-Setup-1.4.2.exe" in text
        assert "has not been published" not in text and "local experimental preview" not in text
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/download/v1.4.2/Halo-Steam-Frame-Mod-Setup-1.4.2.exe" in readme
    notes = (ROOT / "docs/RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert "cannot load old checkpoints" in notes and "save-v1.4" in notes
    sd_guide = (ROOT / "docs/SD_CARD.md").read_text(encoding="utf-8")
    assert "Halo: Combat Evolved VR (Native, SD card)" in sd_guide
    assert "Refresh storage" in readme and "ext4 or f2fs" in sd_guide
    assert "BUILD_PROVENANCE.md" in readme and "BUILD_PROVENANCE.md" in notes


def test_actual_exact_pinned_engine_and_shipped_patch_when_checkout_is_supplied():
    source = os.environ.get("HALO_EXPERIMENTAL_ENGINE_SOURCE")
    if not source:
        pytest.skip("Set HALO_EXPERIMENTAL_ENGINE_SOURCE for the local offline engine integration check")
    result = engine.check_source(Path(source))
    assert result["ok"] and result["protocolVersion"] == 17
    assert result["offlineArm64NinjaGraph"] and result["headDirectedMovementIntegration"]
    assert result["buildRecipeIntegration"]
    assert result["menuControllerRigVisibility"] and result["controllerReticleFallbackSuppressed"]
    assert result["stereoSunGlowIntegration"] and result["vrInternetCampaignMenu"]
    assert result["boundedSunGlowStrength"]
    assert result["nominalProjectileReticleIntegration"]
    assert result["renderRateProjectilePreviewIntegration"]
    assert result["networkCampaignOnlyIntegration"]
    assert result["vrTutorialIntegration"] and result["freshFullPoseTrackingIntegration"]
    assert result["renderRateUnarmedFlashlightIntegration"]
    assert not result["arm64LinkedBuild"] and not result["hardwareValidated"]
