"""Offline source-integration regressions; no game data or headset connection."""
import ast
import importlib.util
import os
from pathlib import Path
import re
import tomllib

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
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    download = re.search(
        r"https://github\.com/ClassicWasTaken/HaloSteamFrameMod/releases/download/[^\s\"<>)]*",
        readme,
    )
    assert download is not None, "README is missing its primary installer download"
    identity = re.fullmatch(
        r"https://github\.com/ClassicWasTaken/HaloSteamFrameMod/releases/download/"
        r"v(?P<version>\d+\.\d+\.\d+)/Halo-Steam-Frame-Mod-Setup-(?P=version)\.exe",
        download.group(),
    )
    assert identity is not None, "README installer tag and filename must share a stable version"
    version = identity["version"]
    filename = f"Halo-Steam-Frame-Mod-Setup-{version}.exe"
    package_version = literal_assignment(ROOT / "src/halo_frame_installer/__init__.py", "__version__")
    build_version = literal_assignment(ROOT / "scripts/build_release.py", "VERSION")
    assert package_version == build_version
    if re.fullmatch(r"\d+\.\d+\.\d+", package_version):
        assert version == package_version, "Stable builds must document their own release download"
        assert tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] == version
    # Private candidates retain the previous public download until publication.
    for name in ("README.md", "docs/SETUP.md", "docs/RELEASE_NOTES.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert version in text and filename in text and download.group() in text
        assert "has not been published" not in text and "local experimental preview" not in text
    notes = (ROOT / "docs/RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert "cannot load old checkpoints" in notes and "save-v1.4" in notes
    sd_guide = (ROOT / "docs/SD_CARD.md").read_text(encoding="utf-8")
    assert "Halo: Combat Evolved VR (Native, SD card)" in sd_guide
    assert "Refresh storage" in readme and "ext4 or f2fs" in sd_guide
    assert "BUILD_PROVENANCE.md" in readme and "BUILD_PROVENANCE.md" in notes


@pytest.fixture
def release_documentation_projection(tmp_path, monkeypatch):
    for relative in ("README.md", "docs/SETUP.md", "docs/RELEASE_NOTES.md", "docs/SD_CARD.md",
                     "src/halo_frame_installer/__init__.py", "scripts/build_release.py", "pyproject.toml"):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    public_version = re.search(r"/releases/download/v(\d+\.\d+\.\d+)/", (tmp_path / "README.md").read_text(encoding="utf-8")).group(1)
    for relative, name in (("src/halo_frame_installer/__init__.py", "__version__"),
                           ("scripts/build_release.py", "VERSION")):
        path = tmp_path / relative
        old = literal_assignment(path, name)
        path.write_text(path.read_text(encoding="utf-8").replace('"' + old + '"', '"' + public_version + '"'), encoding="utf-8")
    project = tmp_path / "pyproject.toml"
    old = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"]
    project.write_text(project.read_text(encoding="utf-8").replace('version = "' + old + '"',
                                                                 'version = "' + public_version + '"', 1), encoding="utf-8")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    return tmp_path


def test_public_release_documentation_rejects_a_stale_download_for_a_stable_build(release_documentation_projection):
    readme = release_documentation_projection / "README.md"
    version = literal_assignment(release_documentation_projection / "scripts/build_release.py", "VERSION")
    text = readme.read_text(encoding="utf-8")
    readme.write_text(text.replace("/v" + version + "/Halo-Steam-Frame-Mod-Setup-" + version + ".exe",
                                   "/v0.0.1/Halo-Steam-Frame-Mod-Setup-0.0.1.exe"), encoding="utf-8")
    with pytest.raises(AssertionError, match="Stable builds must document their own release"):
        test_public_release_documentation_names_the_single_installer_download()


def test_private_candidate_keeps_the_existing_public_download(release_documentation_projection):
    for relative, name in (("src/halo_frame_installer/__init__.py", "__version__"),
                           ("scripts/build_release.py", "VERSION")):
        path = release_documentation_projection / relative
        version = literal_assignment(path, name)
        path.write_text(path.read_text(encoding="utf-8").replace('"' + version + '"',
                                                                '"' + version + '-Test"'), encoding="utf-8")
    test_public_release_documentation_names_the_single_installer_download()


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
