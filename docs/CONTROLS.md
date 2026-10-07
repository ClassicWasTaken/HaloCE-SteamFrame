# Steam Frame controls — 1.4.3

Point the right controller to aim; on foot, the left stick moves relative to your headset's horizontal direction. These Xbox-style controls assume the game's default profile button layout. Driver-seat controls are listed below.

| Frame input | Action |
| --- | --- |
| Left stick | Move relative to headset direction |
| Left stick click | Crouch |
| Right stick left/right | Turn |
| Right stick click | Halo's original weapon zoom |
| Right trigger | Fire |
| Left trigger | Throw grenade |
| A | Jump; accept a menu selection |
| B | Melee; go back in menus |
| X | Reload/use; hold for context actions such as exchanging a weapon |
| Y | Change weapon |
| Left bumper | Change grenade type |
| Right bumper | Toggle flashlight |
| Left controller's d-pad | Navigate menus |
| View | Scoreboard/back |
| Menu | Pause |
| Both grips held | Recenter outside driver seats; release a held foregrip first |
| Left grip near a long gun's foregrip | Aim the gun with both hands |

Install and Repair apply controller aiming, standing height, snap turning and physical punch-to-melee. **B** also remains available for on-foot melee. A fresh install uses 30-degree snap turns, 72 Hz, resolution scale 1.0 and two-handed aiming. Repair keeps other preferences, including snap angle, player height and refresh rate. Use **Pause > VR Setup** or **Settings > VR Setup** to change supported options; smooth turning remains available. Zoomable weapons use Halo's original zoom and HUD, with direct controller aiming. The experimental gun-mounted scope and custom zoom smoothing have been removed. Some display changes require restarting the game.

## Vehicles

Your head looks around freely while the seated view follows the vehicle's full pitch, roll and bounce. Entering a seat captures a separate forward-facing reference and uses its authored camera where available. Hold **View/Back for one second** to recenter after physically sitting down. Your standing reference is retained when you exit.

| Seat | Controls |
| --- | --- |
| Warthog driver | Hold **A** for gas and **B** to brake. Left-stick left/right steers; backward selects reverse, even with A held. Left-stick forward also works. B takes priority over gas and reverse. |
| Ghost driver | Left stick forward/reverse and strafe; right stick turns. |
| Scorpion driver | Left stick forward/reverse; right stick aims the turret and guides the hull as in Halo's original controls. |
| Banshee pilot | Left stick throttle; right stick yaw/pitch using your flight-inversion setting. |
| Gunner or passenger | Existing controller aiming, Xbox buttons and contextual use/exit. |

For the optional Warthog wheel, hold both grips with your hands apart, then rotate the line between them like a steering wheel: clockwise steers right. Looking sideways does not steer. Hold A for gas, B for braking, or use stick throttle. Release either grip to return to stick steering. Release A and both grips once after boarding, closing a menu or recovering tracking before re-engaging. Driver input stops on tracking or focus loss; release the right stick after exiting to resume ordinary on-foot turning. Physical punches do not trigger Warthog braking.

The occupied Warthog windshield is hidden only in the local first-person VR view. Scripted flights and unrecognized vehicles retain their existing controls.

## Menus and aiming

Opening Pause hides gameplay hands, gun, reticle and zoom overlays. The menu stays level and captures your current gaze and position; close/reopen or recenter to place it in front again. Point the right controller at a menu, release its trigger, then press to select. A/B and the d-pad still navigate.

Valid controller poses continue to aim when your hands leave the headset's view. Missing right-controller tracking hides the gameplay rig and controller reticle until tracking returns; a missing left-controller pose hides only that hand. A ray pointing behind you or outside the displayed image does not create a centered HUD reticle. Visible first-person hands and weapons also remain tracked during scripted fly-ins.

When a weapon is equipped, the reticle previews the nominal primary shot using Halo's firing calculation and projectile collision mask. On foot it uses render-frame aim, so its direction is no longer limited to the unit's 30 Hz updates; the hit is traced anew each frame. The headset tester confirmed this behavior in the 1.4.0 baseline. Random spread and ballistic motion can still move individual impacts away from that point. Stereo sun glow defaults to `vr.sun_glow_strength = 0.5` in `config.toml`; 0 disables its glow, and 1 restores full intensity. Repair preserves a custom value.

Before a weapon is equipped, the flashlight also follows the rendered aiming hand with bounded elevation. Its presentation uses current light bounds without changing the simulation's light state. Equipped weapons keep their original flashlight markers.

## Local changes to upstream

The [included patch](../resources/frame-controls.patch) includes these controls and menu changes:

1. It sets **LB = change grenade** and **RB = flashlight**. The pinned upstream branch assigns those two bumpers the other way around.
2. Before a weapon is equipped, the unarmed/default reticle follows the aiming hand. Look at the first mission's technician with your headset. The five calibration dots also recognize pointing with the hand reticle, using the original five-degree target cone. Cryopod look calibration accepts physical headset movement and legitimate snap/smooth stick turns, while ignoring tracking jitter and recenter/menu/cinematic transitions. Follow the technician's instructions and look up, down, left or right as requested. These tutorial inputs do not add head rotation to the equipped weapon's aim or change the campaign difficulty.
3. On foot, left-stick movement follows the headset's horizontal heading while your weapon still follows the controllers. Tracking loss suppresses walking instead of producing arbitrary movement. Driver seats use the vehicle controls above. Set `vr.movement = "aim"` (or `HALO_VR_MOVEMENT=aim`) to restore aim-relative movement; the installer defaults to `vr.movement = "head"`.

4. **Multiplayer > CO-OP CAMPAIGN** offers **HOST LOCAL (LAN)**, **JOIN LOCAL (LAN)**, **HOST ONLINE (INTERNET)**, **JOIN ONLINE (INTERNET)**, and **JOIN INVITE LINK**. Choose a host route, then campaign level and difficulty. Your friend uses the corresponding join route. Online hosting stays private by default; **LISTING = PUBLIC** allows server-browser joining by anyone. Each machine has one campaign player in VR and flat mode; campaign has no second-controller or split-screen option. See the [co-op setup guide](SETUP.md#online-campaign-co-op-with-a-friend).

The game's Steam shortcut also suppresses Steam's duplicate virtual Xbox gamepad with `SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0`. Frame controller poses, buttons and haptics still use OpenXR. This setting applies only to this Halo shortcut.

## First launch

Keep Steam Home and the headset runtime awake during setup. Launch **Halo: Combat Evolved VR (Native)**, or its **SD card** entry, from the Frame's library. 1.4.3 keeps existing 1.4.x profiles and saves in the selected installation's `save-v1.4`. When upgrading from 1.3.5, create a new profile and campaign because its old checkpoints are incompatible and setup does not migrate those profiles. Use the d-pad to select menu items and **A** to accept.

For a control issue, first check **Settings > Gamepads** for a changed profile layout. Then check **Settings > VR Setup**: this layout uses controller aiming. Upstream also offers gamepad aiming, which moves aim with the right stick and has different camera behavior.

The original controls and all VR configuration options are documented in the [pinned upstream VR guide](https://github.com/startupfoundry/halo-ce-universal/blob/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/port/linux/README.md#vr). The [SDL hint source](https://github.com/libsdl-org/SDL/blob/release-3.4.16/include/SDL3/SDL_hints.h) documents virtual-gamepad filtering.
