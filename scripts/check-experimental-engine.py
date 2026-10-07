"""Offline checks of the pinned experimental engine and shipped local patch.

Reads a local vanilla/patched checkout. Applies the patch only to a temporary
projection and generates the real ARM64 Ninja graph without fetching tools,
compiling a game, using retail data, or connecting a headset.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4"
PATCH_FILES = frozenset((
    "port/linux/src/vr.c", "port/linux/src/vr.h", "port/linux/src/vr_locomotion.h",
    "port/linux/src/port_config.c", "source/game/player_control.c", "tools/test_vr_locomotion.py",
    "port/linux/game/menu_functions.c", "port/linux/game/vr_render.c",
    "port/linux/src/d3d8_gl.c", "port/linux/src/nv2a_psh.c", "port/linux/src/xgpu.h",
    "source/rasterizer/xbox/rasterizer_xbox_lights.c",
    "tools/test_online_coop_menu.py", "tools/test_vr_sun_glow.py",
    "source/items/weapons.c", "source/items/weapons.h",
    "source/game/aim_assist.c", "source/game/aim_assist.h",
    "tools/test_vr_projectile_reticle.py",
    "port/assets/menus/ce/main_menu.multiplayer_type_select.coop.xml", "tools/port_settings.py",
    "source/units/units.c", "source/units/units.h",
    "source/hs/hs_library_external.c", "port/linux/arm64/host_vr.c",
    "tools/test_vr_tutorial.py", "tools/test_vr_tracking.py", "tools/test_vr_tutorial_buttons.py",
    "source/objects/object_lights.c", "tools/test_vr_flashlight.py", "tools/test_vr_menu.py",
    "tools/android_build.py", "tools/test_build_sources.py",
    "port/android/guest/runtime/guest_host.h", "port/android/host/host_gl.c",
    "port/linux/arm64/host_imports.list", "port/linux/src/vr_vehicle.h",
    "source/interface/ui_widget.c", "source/interface/motion_sensor.c",
    "source/rasterizer/rasterizer_transparent_geometry.c",
    "port/linux/game/menu_tags.c", "tools/ce_menus.py",
    "port/assets/menus/ce/bitmaps.xml", "port/assets/menus/menus.json",
    "port/assets/menus/ce/main_menu.settings_select.player_setup.player_profile_edit.vr_display.xml",
    "port/assets/menus/ce/port/pause/pausebox_left__2.png",
    "port/assets/menus/ce/port/pause/pausebox_center__2.png",
    "port/assets/menus/ce/port/pause/pausebox_right__2.png",
    "port/assets/menus/port_svg/pause/pausebox_left__2.svg",
    "port/assets/menus/port_svg/pause/pausebox_center__2.svg",
    "port/assets/menus/port_svg/pause/pausebox_right__2.svg",
    "tools/test_vr_pause_menu.py", "tools/test_vr_pointer_radar.py",
    "tools/test_persistent_stream_buffers.py", "tools/test_vr_vehicle.py",
    "tools/test_vr_cinematic_hands.py",
    "port/linux/src/vr_host.h", "source/render/render.c",
    "tools/test_vr_zoom_aim.py", "tools/test_vr_stock_zoom_hud.py",
    "port/linux/src/gl.h", "tools/test_vr_renderer_link.py",
    "port/linux/src/vr_driving.h", "tools/test_vr_driving.py", "tools/test_vr_driving_game.py",
    "port/linux/game/vr_hands.c", "port/linux/game/vr_hands.h",
    "tools/test_vr_framebuffer.py", "tools/test_vr_vehicle_pose.py",
    "source/interface/first_person_weapons.c", "source/interface/hud_weapon.c",
))


class EngineCheckError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise EngineCheckError(message)


def git(source, *arguments, check=True):
    result = subprocess.run(["git", "-C", str(source), *arguments], capture_output=True, timeout=30)
    if check:
        require(result.returncode == 0, "A local Git source check failed; no engine files were changed.")
    return result


def patch_files(text):
    files = re.findall(r"^diff --git a/(\S+) b/(\S+)$", text, re.M)
    require(bool(files), "The local engine patch has no ordinary file diffs.")
    for before, after in files:
        require(before == after and after in PATCH_FILES,
                "The engine patch changes a path outside the reviewed integration files.")
    return frozenset(after for _, after in files)


def c_function(text, name):
    # Keep offsets while hiding comments and string contents from brace counting.
    comments = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
    clean = comments.sub(lambda match: " " * len(match.group()), text)
    masked = re.sub(r'"(?:\\.|[^"\\])*"', lambda match: " " * len(match.group()), clean)
    start = re.search(r"\b" + re.escape(name) + r"\s*\([^;{}]*\)\s*\{", masked)
    require(start is not None, "Missing engine function: " + name)
    depth = 1
    for offset in range(start.end(), len(masked)):
        depth += (masked[offset] == "{") - (masked[offset] == "}")
        if not depth:
            return clean[start.end():offset]
    raise EngineCheckError("Unterminated engine function: " + name)


def check_texture_binding(text):
    body = c_function(text, "bind_textures")
    loops = list(re.finditer(r"for\s*\(stage\s*=\s*0;\s*stage\s*<\s*D3DTSS_MAXSTAGES;\s*stage\+\+\)", body))
    bindings = list(re.finditer(r"\bstate_texture\s*\(", body))
    require(len(loops) == 2 and len(bindings) == 1 and bindings[0].start() > loops[1].start(),
            "Texture binding is not delayed until the second complete stage pass.")
    resolve = body.find("xgpu_texture_get(")
    require(loops[0].start() < resolve < loops[1].start(),
            "Texture uploads must finish before the final stage-binding pass.")
    require("state_texture(stage, gl_targets[stage], gl_textures[stage])" in body,
            "Final texture bindings do not use the resolved per-stage arrays.")


def check_upstream(source):
    read = lambda path: (source / path).read_text(encoding="utf-8")
    limits = read("port/linux/include/halo_port_limits.h")
    require(re.search(r"^#define HALO_PORT_NETWORK_VERSION 17\s*$", limits, re.M),
            "The candidate must use native peer protocol 17.")
    check_texture_binding(read("port/linux/src/d3d8_gl.c"))
    shader = read("port/linux/src/nv2a_vsh.c")
    require("clip_position = oPos" in shader and "clip_captured = true" in shader
            and "if (!(abs(position.w) > 0.0))" in shader
            and "position = vec4(0.0, 0.0, 0.0, -1.0)" in shader,
            "The pinned vertex clip-position safeguards are missing.")
    distributed = read("port/linux/game/network_distributed.c")
    coop = read("port/linux/game/network_coop.c")
    for hook in ("network_coop_host_tick", "network_coop_client_tick", "network_coop_handle_presentation", "network_coop_handle_events"):
        require(hook + "(" in distributed and hook in coop, "Missing integrated co-op hook: " + hook)
    config = read("port/linux/src/port_config.c")
    require('"network.coop_enemies_mode"' in config and '"network.coop_enemies"' in config
            and '"network.brokers_file"' in config, "Co-op/broker configuration is missing.")
    require((source / "port/assets/network/brokers.txt").is_file(), "The candidate broker list is missing.")
    require("saved games of builds before it no longer load" in read("port/linux/include/halo_port_capacity.h"),
            "The candidate saved-game layout change needs explicit compatibility handling.")


def check_controls(source):
    read = lambda path: (source / path).read_text(encoding="utf-8")
    vr = read("port/linux/src/vr.c")
    config = read("port/linux/src/port_config.c")
    require(re.search(r'"vr\.movement",\s*_config_string,\s*"\\"head\\"",\s*"HALO_VR_MOVEMENT"', config),
            "Head-directed walking is not the configurable default.")
    movement = c_function(vr, "halo_vr_locomotion")
    for guard in ("!vr.initialized", "!settings.head_movement", "!settings.controller_aim", "settings.gamepad_aim"):
        require(guard in movement, "Missing unchanged-input mode guard: " + guard)
    for guard in ("vr.views.focused", "vr.views.head.valid", "vr.origin_valid", "vr.aim_synced", "!vr.menus", "halo_vr_locomotion_orientation"):
        require(guard in movement, "Missing valid-tracking locomotion guard: " + guard)
    require("halo_vr_locomotion_project(" in movement, "The tested production movement math is not wired into VR input.")
    player = read("source/game/player_control.c")
    handling = c_function(player, "handle_one_player_input")
    call = handling.find("halo_vr_locomotion(player->desired_angles.yaw")
    require(call >= 0 and handling.find("player->desired_angles.yaw = vr_yaw") < call
            < handling.find("player->throttle = input.throttle"),
            "Movement must be transformed after aiming and before the player/action throttle is stored.")
    guard = handling[max(0, call - 300):call]
    for condition in ("local_player_index == 0", "unit->object.parent_object_index == NONE", "!director_inhibited_facing", "!cinematic_in_progress"):
        require(condition in guard, "Missing local on-foot movement gate: " + condition)
    gamepad = c_function(vr, "halo_vr_gamepad")
    require("XINPUT_GAMEPAD_WHITE, buttons & VR_BUTTON_RIGHT_BUMPER" in gamepad
            and "XINPUT_GAMEPAD_BLACK, buttons & VR_BUTTON_LEFT_BUMPER" in gamepad,
            "The agreed Xbox bumper layout was not preserved.")
    require("halo_vr_tutorial_look(" in c_function(player, "player_control_action_test_note"),
            "The physical-head tutorial hook was not ported to the new co-op action test.")
    c_function(vr, "halo_vr_tutorial_look")
    require((source / "port/linux/src/vr_locomotion.h").is_file(), "The production locomotion header is missing.")


def check_stereo_glow_and_online_menu(source):
    read = lambda path: (source / path).read_text(encoding="utf-8")
    lights = read("source/rasterizer/xbox/rasterizer_xbox_lights.c")
    draw = c_function(lights, "rasterizer_sun_glow_draw")
    require("vr_render_sun_glow_begin(" in draw and "vr_render_sun_glow_end(" in draw,
            "The per-eye sun-glow wrapper is not integrated into the actual renderer.")
    require('config_real("vr.sun_glow_strength")' in draw
            and 'rasterizer_sun_glow_draw_internal(flare, 1.0f)' in draw,
            "The VR sun-strength option must preserve the original flat-screen composite.")
    strength = c_function(lights, "rasterizer_vr_sun_glow_strength")
    require("isfinite(configured)" in strength and "configured < 0.0" in strength
            and "configured > 1.0" in strength and "return 0.5f" in strength,
            "Sun-glow intensity must reject non-finite values and stay within 0–1.")
    require('"vr.sun_glow_strength", _config_real, "0.5"' in read("port/linux/src/port_config.c"),
            "The bounded half-strength sun-glow default is missing.")
    renderer = read("port/linux/game/vr_render.c")
    begin = c_function(renderer, "vr_render_sun_glow_begin")
    for integration in ("vr_render.eye_cameras[eye]", "vr_render.eyes[eye]", "halo_vr_screen_space(1)", "halo_vr_draw_eye(eye)"):
        require(integration in begin, "Missing per-eye glow state: " + integration)
    require("halo_vr_screen_space(0)" in c_function(renderer, "vr_render_sun_glow_end"),
            "Glow screen-space state is not restored.")
    backend = c_function(read("port/linux/src/d3d8_gl.c"), "prepare_draw")
    require(0 <= backend.find("key.sample_eye") < backend.find("fragment_shader_get(&key)"),
            "Source-eye selection must participate in the actual fragment cache key.")
    shader = read("port/linux/src/nv2a_psh.c")
    require("key->multiview == XGPU_MULTIVIEW_NONE && key->sample_eye" in shader,
            "A mono glow scratch target does not sample the selected stereo source eye.")
    menu = read("port/linux/game/menu_functions.c")
    route = c_function(menu, "cooperative_begin")
    routes = {
        "coop_host_lan": "cooperative_network_host(widget, event, controller, _multiplayer_mode_host_lan, widget_deleted)",
        "coop_host_online": "cooperative_network_host(widget, event, controller, _multiplayer_mode_host_internet, widget_deleted)",
        "coop_join_lan": "cooperative_network_join(widget, controller, _multiplayer_mode_lan, widget_deleted)",
        "coop_join_online": "cooperative_network_join(widget, controller, _multiplayer_mode_server_browser, widget_deleted)",
        "coop_join_invite": "cooperative_network_join(widget, controller, _multiplayer_mode_direct_link, widget_deleted)",
    }
    for name, call in routes.items():
        require(re.search(r'if \(!strcmp\(widget->name, "' + name + r'"\)\)\s*return ' + re.escape(call) + r';', route),
                "Missing LAN/Internet campaign dispatch: " + name)
    require("cooperative_session_cleanup();" in route and '"network_screen"' in route,
            "Leaving the campaign network chooser must clean up its pending session.")
    single_player = c_function(menu, "cooperative_single_player")
    for integration in ("player_spawn_count = 1", "player_ui_reset_single_player_local_player_controllers()",
                        "lobby_join_reset()", "player_ui_local_player_left_multiplayer_game(controller)"):
        require(integration in single_player, "Missing one-player campaign reset: " + integration)
    host = c_function(menu, "cooperative_network_host")
    require('mode == _multiplayer_mode_host_internet && !config_boolean("network.online")' in host
            and "multiplayer_host_mode(widget, event, controller, mode, TRUE, widget_deleted)" in host
            and "cooperative_map_opening = TRUE" in host and "cooperative_map_opening = FALSE" in host,
            "Campaign hosts must distinguish offline LAN from Internet and open campaign maps.")
    join = c_function(menu, "cooperative_network_join")
    require('mode != _multiplayer_mode_lan && !config_boolean("network.online")' in join
            and "cooperative_network_game = TRUE" in join and "multiplayer.mode = mode" in join,
            "Campaign joins must distinguish LAN, Internet browser and invite modes.")
    handler = c_function(menu, "pc_menu_event_function_invoke")
    require(re.search(r'else if \(!strcmp\(name, "port coop begin"\)\)\s*\{\s*return cooperative_begin\(', handler),
            "Campaign dispatch must work in both flat and VR builds.")
    require(re.search(r'else if \(!strcmp\(name, "port coop player 2 list initialize"\)[^{]+\{\s*return campaign_fail\(\);', handler)
            and "player_spawn_count = 2;" not in menu and "vr_cooperative_begin" not in menu,
            "Stale split-screen campaign routes must be rejected.")
    for helper in ("lobby_add_player", "lobby_join_start", "lobby_player_choose", "preview_add"):
        body = c_function(menu, helper)
        require("lobby_campaign_single_player()" in body and "return campaign_local_player_block();" in body,
                "Campaign must block a second local player: " + helper)
    require("lobby_local_player_count() > 1" in c_function(menu, "map_list_choose")
            and "cooperative_single_player()" in c_function(menu, "multiplayer_game_player"),
            "Ordinary map/browser entry points must also use one local campaign player.")
    require('!strcmp(name, "gamespy back handler") && cooperative_network_game &&' in handler
            and "!global_network_game_server_get()" in handler,
            "Browser cancellation must preserve a host when returning from Server Setup.")
    asset = source / "port/assets/menus/ce/main_menu.multiplayer_type_select.coop.xml"
    nodes = {node.attrib["name"].rsplit("/", 1)[-1]: node for node in ET.parse(asset).getroot()}
    require("player_2_profile_screen" not in nodes and "player_2_profile_list" not in nodes,
            "The campaign menu must not open a second-player profile screen.")
    for event in ("a", "start"):
        item = nodes["multiplayer_type_coop_item"].find('on[@event="' + event + '"]')
        require(item is not None and item.get("run") == "port coop begin"
                and item.get("open", "").endswith("coop/network_screen"),
                "The campaign button must open the LAN/Internet chooser.")
    captions = {"coop_host_lan": "HOST LOCAL (LAN)", "coop_join_lan": "JOIN LOCAL (LAN)",
                "coop_host_online": "HOST ONLINE (INTERNET)", "coop_join_online": "JOIN ONLINE (INTERNET)",
                "coop_join_invite": "JOIN INVITE LINK"}
    for name, caption in captions.items():
        require(name in nodes and nodes[name].get("text") == caption, "Missing campaign menu choice: " + caption)
        for event in ("a", "start"):
            item = nodes[name].find('on[@event="' + event + '"]')
            require(item is not None and item.attrib == {"event": event, "run": "port coop begin"},
                    "Campaign choices must dispatch their named route without a static widget fallback.")
    generator = read("tools/port_settings.py")
    generated_coop = generator.split("def _coop() -> list:", 1)[1].split("def _item_options_extras", 1)[0]
    require(all(name in generated_coop for name in captions) and "network_screen" in generated_coop
            and "player_2_profile_screen" not in generated_coop,
            "The menu generator must retain the network-only campaign choices.")
    for script in ("tools/test_vr_sun_glow.py", "tools/test_online_coop_menu.py"):
        require((source / script).is_file(), "Missing production C regression: " + script)


def check_nominal_projectile_reticle(source):
    read = lambda path: (source / path).read_text(encoding="utf-8")
    weapons = read("source/items/weapons.c")
    firing = c_function(weapons, "trigger_create_projectiles")
    require(re.search(r"trigger_adjust_projectile_ray\([^;]+&error,\s*FALSE,\s*NULL\)", firing),
            "Real shots must retain the shared firing calculation with target recording.")
    preview = c_function(weapons, "weapon_preview_projectile_ray")
    require(re.search(r"trigger_adjust_projectile_ray\([^;]+&error,\s*TRUE,\s*pose\)", preview),
            "The reticle must use the same pre-spread calculation in preview mode.")
    require(not re.search(r"\b(?:random|projectile_new|weapon_trigger_fire)\w*\s*\(", preview),
            "Reticle preview must not fire or consume shot randomness.")
    assist = read("source/game/aim_assist.c")
    require("player_aim_projectile_internal(player_index, position, direction, FALSE, pose)"
            in c_function(assist, "player_preview_projectile_aim"),
            "Reticle preview must suppress player targeting metadata writes.")
    require("player_aim_projectile_internal(player_index, position, direction, TRUE, NULL)"
            in c_function(assist, "player_aim_projectile"),
            "Actual shots must preserve player targeting metadata writes.")
    renderer = read("port/linux/game/vr_render.c")
    crosshairs = c_function(renderer, "vr_render_crosshairs")
    point = c_function(renderer, "vr_render_projectile_point")
    require("vr_render_projectile_point(" in crosshairs and "vr_render_projectile_ray(" in point
            and "_collision_test_for_projectiles_flags" in point,
            "The rendered reticle must trace the game's nominal projectile ray.")
    require("MAXIMUM_COLLISION_USER_STACK_DEPTH - 2" in point,
            "The reticle must reserve capacity for UI, aim-assist and nested line-of-sight contexts.")
    require("weapon_preview_projectile_ray(weapon_index, 0, player_index"
            in c_function(renderer, "vr_render_projectile_ray"),
            "The reticle must query the equipped primary weapon's actual firing ray.")
    require("crosshair_inverse_distance" not in crosshairs and "CROSSHAIR_SMOOTHING" not in crosshairs,
            "Reticle depth must not lag behind its current collision hit.")
    require((source / "tools/test_vr_projectile_reticle.py").is_file(),
            "The production projectile-reticle regression is missing.")
    pose = c_function(renderer, "vr_render_pointing_pose")
    for guard in ("local_player_get_player_index(0)", "_object_type_biped", "parent_object_index != NONE",
                  "gunner_object_index != NONE", "_director_perspective_first_person", "director_inhibited_facing(0)",
                  "aiming_velocity_maximum != 0.0f", "aiming_acceleration_maximum != 0.0f"):
        require(guard in pose, "Missing guarded render-rate preview state: " + guard)
    for integration in ("view->hand_forward", "player_control_get_facing_direction(0",
                        "DEGREES_TO_RADIANS(85.0f)", "unit_clip_to_aiming_bounds(",
                        "render_interpolation_camera(0, observer_get_camera(0))"):
        require(integration in pose, "Missing current-frame preview input: " + integration)
    require("hand_position" not in pose and "camera_effects" not in pose,
            "Preview origin must not add hand translation or apply camera effects again.")
    require("vr_render_pointing_pose(player_index, unit, &vr_render.view, vr_render.base_yaw, pose)"
            in c_function(renderer, "vr_render_projectile_pose"),
            "The equipped reticle must retain the current render pose and yaw.")
    unarmed = c_function(renderer, "vr_render_unarmed_ray")
    require("unit_get_weapon_count(unit_index) != 0" in unarmed
            and "_object_dead_bit" in unarmed and "unit->unit.player_index != player_index" in unarmed
            and "unit_inventory_get_weapon" in unarmed and "vr_render_pointing_pose(" in unarmed,
            "An unarmed reticle must be limited to a living owned player without an equipped weapon.")
    ray = c_function(renderer, "vr_render_projectile_ray")
    require("vr_render_projectile_pose(player_index, unit, &pose) ? &pose : NULL" in ray,
            "The current-frame pose is not integrated into the primary reticle preview.")
    units = read("source/units/units.c")
    require("adjust_origin, use_aiming_vector, NULL, NULL" in c_function(units, "unit_adjust_projectile_ray"),
            "Actual unit shots must not use presentation overrides.")
    require("unit_adjust_projectile_ray_internal(" in c_function(units, "unit_preview_projectile_ray"),
            "Unit preview must share the original camera/muzzle projection math.")


def check_unarmed_flashlight(source):
    read = lambda path: (source / path).read_text(encoding="utf-8")
    renderer = read("port/linux/game/vr_render.c")
    pose = c_function(renderer, "vr_render_player_flashlight_pose")
    for guard in ("!vr_render.active", "!vr_render.weapon_camera_set",
                  "!vr_render.weapon_camera_valid", "render.local_player_index != 0",
                  "director_camera_scripted && *director_camera_scripted",
                  "!halo_vr_aiming()", "!halo_vr_gaze_tracking_valid()",
                  "vr_render_unarmed_ray("):
        require(guard in pose, "Missing unarmed flashlight render-pose guard: " + guard)
    require("vr_render.weapon_camera.position" in pose and "vr_render.weapon_camera.up" in pose
            and "dot_product3d(" in pose and "normalize3d(" in pose
            and "halo_vr_view(" not in pose,
            "The flashlight must use the cached rendered hand pose with a perpendicular up vector.")
    lights = read("source/objects/object_lights.c")
    override = c_function(lights, "light_vr_unarmed_flashlight_pose")
    for guard in ("#ifdef HALO_VR", "light->parent_light_index == NONE",
                  "light->object_index != NONE", "_point_light_dynamic_bit",
                  "_light_definition_is_first_person_flashlight_bit",
                  "vr_render_player_flashlight_pose("):
        require(guard in override, "Missing local flashlight light-definition guard: " + guard)
    bounds = c_function(lights, "light_compute_render_bounding_sphere")
    require("struct light_datum effective = *light_get(light_index)" in bounds
            and "&effective.position" in bounds and "&effective.forward" in bounds
            and "light_compute_bounding_sphere_from_basis(&effective" in bounds,
            "Render flashlight bounds must use a copy of the simulation light.")
    simulation = c_function(lights, "light_compute_bounding_sphere")
    reconnect = c_function(lights, "light_reconnect_to_map")
    require("light_compute_bounding_sphere_from_basis(light_get(light_index)" in simulation
            and "light_compute_render_bounding_sphere(" not in reconnect
            and "light_vr_unarmed_flashlight_pose(" not in reconnect,
            "Flashlight presentation must not move the simulation light's BSP partition.")
    include = c_function(lights, "lights_vr_include_unarmed_flashlights")
    require("light_unmarked(light_index)" in include and "object_get_function_value(" in include
            and "intensity <= 0.0f" in include and "slot < MAXIMUM_RENDERED_LIGHTS" in include
            and "MAXIMUM_RENDERED_LIGHTS - 1" in include,
            "Adding a local flashlight outside stale visibility must respect scene-list capacity.")
    preprocess = c_function(lights, "lights_preprocess_scene")
    require(0 <= preprocess.find("structure_visibility_find_objects(")
            < preprocess.find("lights_vr_include_unarmed_flashlights()")
            < preprocess.find("light_marker_end()"),
            "The current flashlight must be included before finishing scene-light visibility.")
    require("light_vr_unarmed_flashlight_pose(light, &light_parameters.position" in preprocess
            and "first_person_weapon_center_flashlight(" in preprocess,
            "The local unarmed override must be integrated without replacing armed flashlight markers.")
    for name in ("light_get_bounding_sphere", "lights_render_diffuse", "lights_render_specular"):
        require("light_compute_render_bounding_sphere(" in c_function(lights, name),
                "Flashlight visibility and drawing must share rendered bounds: " + name)
    for name in ("lights_render_diffuse", "lights_render_specular"):
        require("light_render_skips_clusters(light)" in c_function(lights, name),
                "The unarmed beam must not use stale tick cluster restrictions: " + name)
    require((source / "tools/test_vr_flashlight.py").is_file(),
            "Missing production C flashlight regression.")


def check_tutorial(source):
    read = lambda path: (source / path).read_text(encoding="utf-8")
    player = read("source/game/player_control.c")
    require("halo_vr_turn_control(" in c_function(player, "handle_one_player_input")
            and "halo_vr_tutorial_reset(" in c_function(player, "player_control_action_test_reset")
            and "halo_vr_tutorial_turn(" in c_function(player, "player_control_action_test_note"),
            "The script action tests must share actual VR turns and reset their head anchor.")
    buttons = c_function(player, "player_control_action_test_check_reset_input_blob")
    require("halo_vr_running()" in buttons and "halo_vr_active" not in buttons
            and "vr_controls" in buttons
            and "_unit_control_use_equipment_bit, FALSE" in c_function(player, "player_control_action_test_check_reset_input_blob"),
            "A consumed VR tutorial Back button must suppress its mapped melee action.")
    vr = read("port/linux/src/vr.c")
    c_function(vr, "halo_vr_running")
    require("int halo_vr_running(void);" in read("port/linux/src/vr.h"),
            "The tutorial VR-running query must use the real engine API.")
    units = c_function(read("source/units/units.c"), "unit_can_see_point")
    require("vr_render_player_gaze(" in units and "local_player_index == 0" in units
            and "_object_dead_bit" in units,
            "Headset gaze must be limited to the living local primary player.")
    hs = read("source/hs/hs_library_external.c")
    panel = c_function(hs, "hs_vr_calibration_panel")
    require("degrees != 5.f" in panel and "levels\\\\a10\\\\a10" in panel
            and "_object_type_scenery" in panel,
            "Hand-reticle acceptance must retain the original named a10 panel gate.")
    require("hs_vr_calibration_panel(" in c_function(hs, "hs_unit_can_see_object")
            and "vr_render_player_pointing_ray(" in c_function(hs, "hs_unit_can_see_object"),
            "The unarmed presentation ray must be integrated into the panel check.")
    locate = c_function(read("port/linux/arm64/host_vr.c"), "host_vr_locate")
    require(0 <= locate.find("views->head.valid = 0") < locate.find("if (!vr.frame_begun)")
            and "XR_VIEW_STATE_POSITION_VALID_BIT" in locate
            and "XR_SPACE_LOCATION_POSITION_VALID_BIT" in locate,
            "Fresh full-pose queries must invalidate stale data before any failure return.")
    for script in ("tools/test_vr_tutorial.py", "tools/test_vr_tracking.py", "tools/test_vr_tutorial_buttons.py"):
        require((source / script).is_file(), "Missing tutorial production C regression: " + script)


def check_private_menu_and_vehicle_integration(source):
    read = lambda path: (source / path).read_text(encoding="utf-8")
    config = read("port/linux/src/port_config.c")
    for key, default in (("vr.menu_pointer", "true"), ("vr.radar_head_heading", "true"),
                         ("vr.vehicle_seat_calibration", "true"), ("vr.vehicle_clear_windshield", "true"),
                         ("display.persistent_stream_buffers", "false")):
        require(re.search(re.escape('"' + key + '"') + r',\s*_config_boolean,\s*"' + default + r'"', config),
                "Missing reviewed private option/default: " + key)
    tags = read("port/linux/game/menu_tags.c")
    loaded = c_function(tags, "menu_tags_loaded")
    require("halo_vr_running() && tag_loaded(UI_WIDGET_DEFINITION_TAG, SOLO_PAUSE_SCREEN) != NONE" in loaded
            and "build.multiplayer_map = game_map && multiplayer_map" in loaded,
            "Pause VR Setup must use the exact campaign root and distinguish network-map pause flags.")
    require("if (build.multiplayer_map)" in c_function(tags, "widget_build")
            and "pause_vr_widget()" in c_function(tags, "pause_patch")
            and '"VR SETUP", NONE' in c_function(tags, "pause_list_patch"),
            "Pause VR Setup must reuse existing widgets without a profile-edit or network function.")
    ui = read("source/interface/ui_widget.c")
    require("!network_coop_active()" in c_function(ui, "widget_instance_initialize")
            and "vr_render_menu_pointer_draw()" in c_function(ui, "render_ui_widgets"),
            "Pause settings must retain co-op clock policy and render the native UI pointer.")
    vr = read("port/linux/src/vr.c")
    pointer = c_function(vr, "halo_vr_menu_pointer")
    require("menu_pointer_intersection(" in pointer and "menu_pointer_button(" in pointer
            and "!vr.pending_layers.hud_head_locked" in pointer,
            "The tracked pointer must intersect the fixed rendered menu panel.")
    backend = read("port/linux/src/d3d8_gl.c")
    desktop_pointer = c_function(backend[backend.rfind("int halo_ui_pointer_update"):], "halo_ui_pointer_update")
    require("halo_vr_menu_pointer(menus_active, pointer)" in desktop_pointer,
            "VR pointing must feed the existing native widget input path.")
    renderer = read("port/linux/game/vr_render.c")
    require("vr_render_player_gaze(" in c_function(renderer, "vr_render_motion_sensor_yaw"),
            "Optional head-heading radar must use the current rendered HMD gaze.")
    radar = c_function(read("source/interface/motion_sensor.c"), "render_motion_sensor")
    require("vr_render_motion_sensor_yaw(" in radar and "draw_sensor = *sensor" in radar
            and "render_sensor = &draw_sensor" in radar,
            "Radar head heading must alter a draw copy, preserving tick/history data.")
    display = ET.parse(source / "port/assets/menus/ce/main_menu.settings_select.player_setup.player_profile_edit.vr_display.xml")
    require(any(node.get("setting") == "display.persistent_stream_buffers"
                and node.get("values") == "true|false" for node in display.getroot()),
            "The existing VR Display screen must expose the optional buffer-streaming setting.")
    require("halo_vr_vehicle_reference(" in c_function(renderer, "vr_render_vehicle_reference")
            and "vr_render_vehicle_reference(" in c_function(renderer, "vr_render_camera")
            and "vr_render_vehicle_reference(" in c_function(read("source/game/player_control.c"), "handle_one_player_input"),
            "Seated reference calibration must be integrated into both current view and player input.")
    require("halo_vr_vehicle_update(" in c_function(vr, "halo_vr_vehicle_reference")
            and "vehicle_capture()" in c_function(vr, "recentre")
            and (source / "port/linux/src/vr_vehicle.h").is_file(),
            "Vehicle entry/recenter must use its separate production tracking reference.")
    require("menu_level_orientation(" in c_function(vr, "menu_place"),
            "Menu placement must remove head roll while preserving the gaze direction.")
    seat_camera = c_function(renderer, "vr_render_vehicle_camera_position")
    require("object_get_marker_by_name(" in seat_camera and "isfinite(" in seat_camera
            and "vr_render_vehicle_camera_position(" in c_function(renderer, "vr_render_player_gaze")
            and "vr_render_vehicle_camera_position(" in c_function(renderer, "vr_render_camera"),
            "The local vehicle view and gaze must share a checked seat anchor.")
    presentation = c_function(renderer, "vr_render_controller_presentation")
    require("halo_vr_presentation_tracking_valid()" in presentation
            and "_director_perspective_first_person" in presentation
            and "_object_dead_bit" in presentation
            and "vr_render_controller_presentation()" in c_function(renderer, "vr_render_weapon_camera"),
            "Controller presentation must remain available in a visible first-person arrival rig.")
    tracking = c_function(vr, "halo_vr_presentation_tracking_valid")
    require("vr.views.focused" in tracking and "vr.views.head.valid" in tracking
            and "isfinite(" in tracking and "vr.aim_synced" not in tracking,
            "Presentation must require current finite tracking without enabling gameplay aim.")
    glass = c_function(renderer, "vr_render_hides_vehicle_glass")
    require('"vehicles\\\\warthog\\\\warthog"' in glass and "seated_unit()" in glass
            and "object_index != unit->object.parent_object_index" in glass,
            "The windshield override must be limited to the occupied stock Warthog.")
    transparent = c_function(read("source/rasterizer/rasterizer_transparent_geometry.c"),
                             "rasterizer_transparent_geometry_draw")
    require("_shader_type_transparent_glass" in transparent and "vr_render_hides_vehicle_glass(" in transparent
            and re.search(r"transparent_geometry_group_index\+\+;\s*continue;", transparent),
            "The local glass override must advance the existing draw queue without changing retail tags.")
    for script in ("tools/test_vr_pause_menu.py", "tools/test_vr_pointer_radar.py", "tools/test_vr_vehicle.py",
                   "tools/test_vr_cinematic_hands.py"):
        require((source / script).is_file(), "Missing private production C regression: " + script)


def check_menu_controller_visibility(source):
    """Verify the shipped menu/tracking fix reaches the actual draw paths."""
    read = lambda path: (source / path).read_text(encoding="utf-8")
    vr = read("port/linux/src/vr.c")
    view = c_function(vr, "halo_vr_view")
    require("int controller_aim_requested;" in read("port/linux/src/vr.h")
            and "view->controller_aim_requested = settings.controller_aim" in view,
            "Controller aim mode must remain distinct from current pose validity.")
    require(view.find("view->controller_aim_requested = settings.controller_aim") < view.find("host_vr_locate("),
            "Late tracking failure must retain the selected controller aim mode.")
    renderer = read("port/linux/game/vr_render.c")
    visible = c_function(renderer, "vr_render_first_person_visible")
    crosshairs = c_function(renderer, "vr_render_hud_crosshairs_visible")
    for body in (visible, crosshairs):
        require("halo_vr_frame_active()" in body and "controller_aim_requested" in body,
                "Controller visibility must distinguish native VR mode from flat/gamepad/head paths.")
        require("ui_widgets_active_for_local_player(" in body or "vr_render_gameplay_hud_visible(" in body,
                "Controller visibility must read current menu state before a stale input flag.")
    update = c_function(read("source/interface/first_person_weapons.c"), "first_person_weapon_render_update")
    require("vr_render_first_person_visible(render.local_player_index)" in update
            and update.find("vr_render_first_person_visible(") < update.find("first_person_weapon_set_visibility("),
            "The first-person rig must apply visibility before building or drawing head-camera nodes.")
    hud = c_function(read("source/interface/hud_weapon.c"), "crosshairs_draw")
    require("vr_render_hud_crosshairs_visible(" in hud
            and hud.find("vr_render_hud_crosshairs_visible(") < hud.find("TEST_FLAG(weapon_hud_globals->script_flags"),
            "The ordinary HUD crosshair fallback must share the controller-mode visibility guard.")


def check_optional_native_buffer_streaming(source):
    read = lambda path: (source / path).read_text(encoding="utf-8")
    backend = read("port/linux/src/d3d8_gl.c")
    require("#if defined(HALO_ARM64_GUEST) && !defined(HALO_GLES)\n#define XGPU_PERSISTENT_STREAMS" in backend,
            "Persistent streaming must remain limited to the native desktop-GL guest.")
    initialize = c_function(backend, "stream_buffers_initialize")
    require('config_boolean("display.persistent_stream_buffers")' in initialize
            and "host_gl_buffer_create_persistent(" in initialize
            and "host_gl_buffer_destroy_persistent(" in initialize,
            "Optional streaming must initialize transactionally and retain the ordinary-buffer fallback.")
    frame = c_function(backend, "frame_end_buffers")
    require("host_gl_wait_frame_checked(" in frame and "stream_ring_reset(ring_ready)" in frame,
            "Mapped ring reuse must be gated by a completed host fence.")
    reset = c_function(backend, "stream_ring_reset")
    require("if (!ready)" in reset and "device.persistent_ring[ring] = FALSE" in reset
            and "glGenBuffers(" in reset,
            "An unfinished mapped slot must retire its mappings before mutable reuse.")
    host = read("port/android/host/host_gl.c")
    functions = ("host_gl_buffer_create_persistent", "host_gl_buffer_destroy_persistent",
                 "host_gl_buffer_write_persistent", "host_gl_wait_frame_checked")
    imports = set(read("port/linux/arm64/host_imports.list").splitlines())
    declarations = read("port/android/guest/runtime/guest_host.h") + read("port/linux/src/xgpu.h")
    for function in functions:
        c_function(host, function)
        require(function in imports and function + "(" in declarations,
                "Missing real host definition/import/declaration: " + function)
    create = c_function(host, "host_gl_buffer_create_persistent")
    write = c_function(host, "host_gl_buffer_write_persistent")
    require("#ifdef HALO_DESKTOP_GL" in create and "GL_ARB_buffer_storage" in create
            and "glBufferStorage" in create and "glDeleteBuffers(" in create,
            "Persistent allocation must check desktop capability and delete a failed immutable allocation.")
    require("size > persistent_buffers[slot].size - offset" in write and "size && !data" in write,
            "Host-owned mapped writes must enforce the buffer's recorded range and non-null data.")
    require((source / "tools/test_persistent_stream_buffers.py").is_file(),
            "Missing production host/guest buffer-streaming regression.")


GRAPH_SMOKE = r'''
import io
from pathlib import Path
from types import SimpleNamespace
import sys
import re
sys.path.insert(0, str(Path.cwd()))
from tools import linux_arm64_build as build
from tools.ninja_syntax import Writer
headers = Path(".offline-check-headers")
(headers / "GLES3").mkdir(parents=True)
(headers / "GLES3/gl32.h").write_text("/* graph check only */")
build.GL_HEADERS = headers
build.is_linux_arm64 = lambda: True
build.fetch_third_party = lambda directory: None
sln = SimpleNamespace(port_release=True, port_vr=True, linux_arm64_cc="clang", port_pgo="off", port_lto="off")
output = io.StringIO()
build.generate_linux_arm64_build(Writer(output), sln)
graph = output.getvalue()
# pathlib follows the checker host even though this is a Linux build graph.
# Normalize only the inspected text; retain the actual generated graph below.
inspected_graph = re.sub(r"\$\r?\n[ \t]*", "", graph).replace("\\", "/")
for required in ("port/linux/game/network_coop.c", "port/linux/game/coop_scripts.c", "port/linux/game/coop_enemies.c", "port/linux/src/vr.c", "port/linux/arm64/host_vr.c", "port/linux/game/menu_tags.c", "source/interface/ui_widget.c", "source/interface/motion_sensor.c", "source/rasterizer/rasterizer_transparent_geometry.c", "port/android/host/host_gl.c", "-DHALO_VR=1", "-iquote port/linux/game", "build/linux_arm64/brokers.txt", "port/assets/network/brokers.txt"):
    if required not in inspected_graph:
        raise RuntimeError("The ARM64 graph omitted " + required)
if "-DHALO_GLES=1" in graph:
    raise RuntimeError("The VR guest graph selected GLES instead of desktop OpenGL")
Path(".offline-check-build.ninja").write_text(graph, encoding="utf-8")
print("ARM64/OpenXR guest, host, co-op and broker graph generated without downloads or compilation.")
'''


def project_source(source, destination):
    archive = git(source, "archive", "--format=tar", SOURCE_COMMIT).stdout
    require(len(archive) <= 256 * 1024 * 1024, "The source archive exceeds the offline check limit.")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as entries:
        for entry in entries:
            name = PurePosixPath(entry.name)
            require(not name.is_absolute() and ".." not in name.parts and (entry.isdir() or entry.isfile()),
                    "The source projection contains an unexpected path or link.")
            target = destination.joinpath(*name.parts)
            if entry.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with entries.extractfile(entry) as incoming, target.open("wb") as outgoing:
                    outgoing.write(incoming.read())


def build_recipe_cli_options(candidate: Path, visited=None):
    """Read declared options, including a local test's delegated main parser."""
    visited = set() if visited is None else visited
    if candidate in visited:
        return set()
    require(len(visited) < 32, "Native test CLI delegation exceeds the source check limit.")
    visited.add(candidate)
    try:
        tree = ast.parse(candidate.read_text(encoding="utf-8"), filename=str(candidate))
    except SyntaxError as error:
        raise EngineCheckError("A native build test has invalid Python syntax: " + candidate.name) from error
    options = {argument.value for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
               for argument in node.args if isinstance(argument, ast.Constant)
               and isinstance(argument.value, str) and argument.value.startswith("--")}
    called_main = {node.func.value.id for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute) and node.func.attr == "main"
                   and isinstance(node.func.value, ast.Name)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for imported in node.names:
            if (imported.asname or imported.name) not in called_main:
                continue
            delegate = candidate.parent / (imported.name + ".py")
            if delegate.is_file() and not delegate.is_symlink():
                options.update(build_recipe_cli_options(delegate, visited))
    return options


def check_build_recipe(source: Path, recipe: str | None = None):
    """Check the actual container commands against the canonical patched tree."""
    recipe = recipe if recipe is not None else (ROOT / "resources/build-native.sh").read_text(encoding="utf-8")
    require("set -euo pipefail" in recipe, "The native build recipe must stop on failed checks.")
    commands = []
    for line in recipe.splitlines():
        if re.match(r"^\s*python3\s", line):
            try:
                argv = shlex.split(line, comments=True)
            except ValueError as error:
                raise EngineCheckError("An invalid Python command appears in the native build recipe.") from error
            require(len(argv) >= 2 and all(token not in (";", "||", "&&", "|") for token in argv),
                    "The native build recipe contains an unsupported Python command.")
            commands.append(argv)
    tests = [argv for argv in commands if argv[1].startswith("tools/test_")]
    expected = {path for path in PATCH_FILES if path.startswith("tools/test_") and path.endswith(".py")}
    actual = [argv[1] for argv in tests]
    require(len(actual) == len(set(actual)), "The native build recipe repeats a regression test.")
    require(set(actual) == expected,
            "The native build recipe does not match the shipped engine tests: " +
            ", ".join(sorted(set(actual) ^ expected)))
    for argv in commands:
        path = PurePosixPath(argv[1])
        require(not path.is_absolute() and ".." not in path.parts and path.suffix == ".py",
                "The native build recipe references an unsafe script path.")
        candidate = source.joinpath(*path.parts)
        require(candidate.is_file() and not candidate.is_symlink() and candidate.resolve().is_relative_to(source.resolve()),
                "The native build recipe references a missing script: " + argv[1])
        if argv in tests:
            options = build_recipe_cli_options(candidate)
            require(all(argument in options for argument in argv[2:] if argument.startswith("--")),
                    "The native build recipe passes an unsupported option to " + argv[1])
            if argv[1] != "tools/test_build_sources.py":
                require("--cc" in argv and argv[argv.index("--cc") + 1:argv.index("--cc") + 2] == ["clang"],
                        "The native build recipe must use the installed compiler for " + argv[1])
    configure = [argv for argv in commands if argv[1] == "configure.py"]
    require(configure == [["python3", "configure.py", "--release", "--vr", "--linux-arm64-cc", "clang"]],
            "The native build recipe must configure the release ARM64 VR target exactly once.")
    require(commands[-1] == configure[0], "Native regression checks must complete before configuration.")
    require(re.search(r"^ninja\s+-j4\s+linux_arm64\s*$", recipe, re.M),
            "The native build recipe must build the configured ARM64 target.")
    return actual


def check_source(source: Path):
    source = source.resolve()
    require(git(source, "rev-parse", "HEAD").stdout.decode().strip() == SOURCE_COMMIT,
            "Use the exact pinned experimental engine commit; a moving branch is not accepted.")
    patch = ROOT / "resources/frame-controls.patch"
    changed = patch_files(patch.read_text(encoding="utf-8"))
    dirty = git(source, "diff", "--name-only", "HEAD").stdout.decode().splitlines()
    untracked = git(source, "ls-files", "--others", "--exclude-standard").stdout.decode().splitlines()
    require(set(dirty + untracked) <= changed, "The engine checkout has changes outside the reviewed local patch.")
    vanilla = git(source, "apply", "--check", str(patch), check=False).returncode == 0
    patched = git(source, "apply", "--reverse", "--check", str(patch), check=False).returncode == 0
    require(vanilla or patched, "The local patch neither applies cleanly nor exactly reverses in this checkout.")
    require(not vanilla or not dirty + untracked, "A vanilla source input must have no local engine changes.")
    # Always test a clean canonical projection, so a patched input is not trusted
    # merely because its HEAD still names the selected revision.
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="experimental-engine-check-", dir=ROOT / "build") as temporary:
        projection = Path(temporary)
        project_source(source, projection)
        check_upstream(projection)
        subprocess.run(["git", "init", "--quiet"], cwd=projection, check=True, capture_output=True, timeout=30)
        for arguments in (("--check",), ()):
            result = subprocess.run(["git", "apply", *arguments, str(patch)], cwd=projection,
                                    capture_output=True, timeout=30)
            require(result.returncode == 0, "The local patch does not apply to the canonical pinned engine source.")
        if patched:
            for path in changed:
                actual, expected = (source / path).read_bytes(), (projection / path).read_bytes()
                if not path.endswith(".png"):
                    actual, expected = actual.replace(b"\r\n", b"\n"), expected.replace(b"\r\n", b"\n")
                require(actual == expected,
                        "The patched input contains an extra change beyond the shipped local patch: " + path)
        check_controls(projection)
        check_stereo_glow_and_online_menu(projection)
        check_nominal_projectile_reticle(projection)
        check_tutorial(projection)
        check_unarmed_flashlight(projection)
        check_private_menu_and_vehicle_integration(projection)
        check_menu_controller_visibility(projection)
        check_optional_native_buffer_streaming(projection)
        check_build_recipe(projection)
        result = subprocess.run([sys.executable, "-I", "-c", GRAPH_SMOKE], cwd=projection,
                                capture_output=True, text=True, timeout=30)
        require(result.returncode == 0, "Offline ARM64 configuration generation failed: " + result.stderr[-2000:])
    return {"ok": True, "sourceCommit": SOURCE_COMMIT, "workingTree": "vanilla" if vanilla else "patched",
            "protocolVersion": 17, "rendererTwoPassBinding": True, "campaignCoopIntegration": True,
            "headDirectedMovementIntegration": True, "xboxControlsPreserved": True,
            "stereoSunGlowIntegration": True, "boundedSunGlowStrength": True, "vrInternetCampaignMenu": True,
            "nominalProjectileReticleIntegration": True, "renderRateUnarmedFlashlightIntegration": True,
            "renderRateProjectilePreviewIntegration": True,
            "networkCampaignOnlyIntegration": True,
            "vrTutorialIntegration": True,
            "freshFullPoseTrackingIntegration": True,
            "pauseVRSetupIntegration": True, "trackedVRMenuPointerIntegration": True,
            "menuControllerRigVisibility": True, "controllerReticleFallbackSuppressed": True,
            "renderOnlyHeadRadarIntegration": True, "seatedVehicleReferenceIntegration": True,
            "localWarthogGlassIntegration": True, "optionalNativePersistentBuffersIntegration": True,
            "buildRecipeIntegration": True,
            "offlineArm64NinjaGraph": True, "arm64LinkedBuild": False, "hardwareValidated": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Local exact-pinned vanilla or fully patched engine checkout")
    arguments = parser.parse_args()
    try:
        result = check_source(arguments.source)
    except (EngineCheckError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
