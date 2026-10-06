# Halo CE Steam Frame VR Mod 1.4.1

[**Download Halo-Steam-Frame-Mod-Setup-1.4.1.exe**](https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/download/v1.4.1/Halo-Steam-Frame-Mod-Setup-1.4.1.exe) for Windows 10/11 x64. This is the release's only installer asset. Its SHA256 is listed on the [release page](https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/tag/v1.4.1); matching installer source is in the [v1.4.1 tag](https://github.com/ClassicWasTaken/HaloSteamFrameMod/tree/v1.4.1).

This patch addresses the first mission's VR tutorial:

- **Aim before receiving a weapon:** the unarmed/default reticle follows the tracked aiming hand. Equipped weapons retain the existing nominal bullet-hit alignment and render-rate preview.
- **Look at the technician and panel:** person checks use headset gaze. The five tutorial dots also accept the unarmed hand reticle within their original five-degree target cone.
- **Cryopod look calibration:** look tests reset their tracking correctly and accept headset movement and legitimate snap or smooth stick turns. Recentring, menus and cinematics do not count as tutorial progress; AI and remote players retain their behavior.
- **Standing and snap defaults:** Install and Repair apply standing mode and snap turning. Other preferences, including snap angle and refresh rate, remain intact.
- **Inversion prompt buttons:** tutorial Back no longer leaks into melee or other mapped gameplay actions while pressed or held. The reported crash still needs confirmation in the headset test; the profile's inversion-setting and save logic remain intact.
- **Tracking loss:** a failed or partial OpenXR pose query cannot reuse an old valid head or hand pose to complete a tutorial target.

**Update an existing native installation with Repair.** Save and close Halo, then choose Repair to rebuild the patched game using its verified Xbox maps. The game stays at `~/Games/HaloCENativeVR` with the Steam title **Halo: Combat Evolved VR (Native)**. Existing 1.4.0 profiles and checkpoints remain in `save-v1.4`; this patch does not change the save format.

Upgrading from 1.3.5 retains its old saves and backs up the original config/program. The 1.4 engine cannot load old checkpoints from 1.3.5, so that upgrade requires a new profile and campaign. Setup does not migrate those checkpoints or profiles. The separate 1.4.0a2–a5 Experimental installations remain untouched.

Source remains pinned to `2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4`, native peer protocol **17**. LAN/online campaign, head-directed walking, Xbox-style buttons, stereo sun glow and automatic Steam artwork/Notes are retained. Use matching builds/maps for co-op; retail Halo clients cannot join. Restrictive NAT can prevent Internet connections because there is no gameplay relay.

The earlier headset report verified the 1.4.0 baseline, not these new tutorial changes. This patch needs its own headset verification; automated checks do not establish tutorial behavior or Frame performance on hardware.

Supply your own authorized original Xbox Halo CE data. No retail executable, ISO, maps, keys, or soundtrack is bundled or downloaded. Halo identification artwork and licensed components retain their notices. The EXE is unsigned; verify it against the SHA256 shown on the release page.

[Setup guide](SETUP.md) · [Controls](CONTROLS.md) · [Sources and credits](SOURCES.md) · [Third-party notices](THIRD_PARTY.md) · [Previous 1.4.0 release](https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/tag/v1.4.0)
