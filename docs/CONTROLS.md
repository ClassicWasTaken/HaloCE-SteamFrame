# Steam Frame controls — 1.4.1

1.4.1 uses head-directed walking and tracked controller aiming with Xbox-style buttons. Point the right controller to aim; the left stick moves relative to the horizontal direction of your headset. These controls assume the game's default profile button layout.

| Frame input | Action |
| --- | --- |
| Left stick | Move relative to headset direction |
| Left stick click | Crouch |
| Right stick left/right | Turn |
| Right stick click | Zoom |
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
| Both grips held | Recenter the headset view; release a held foregrip first |
| Left grip near a long gun's foregrip | Aim the gun with both hands |

Install and Repair apply controller aiming, standing height and snap turning. A fresh install uses 30-degree snap turns, 72 Hz, resolution scale 1.0 and two-handed aiming. Repair keeps your other preferences, including snap angle, player height and refresh rate. Gesture melee is disabled so **B** remains the predictable melee input. You can change supported options in **Settings > VR Setup** or the game's `config.toml`; smooth turning remains available. Some display changes require restarting the game.

When a weapon is equipped, the reticle previews the nominal primary shot using Halo's firing calculation and projectile collision mask. On foot it uses render-frame aim, so its direction is no longer limited to the unit's 30 Hz updates; the hit is traced anew each frame. The headset tester confirmed this behavior in the 1.4.0 baseline. Random spread and ballistic motion can still move individual impacts away from that point. Stereo sun glow defaults to `vr.sun_glow_strength = 0.5` in `config.toml`; 0 disables its glow, and 1 restores full intensity. Repair preserves a custom value.

## Local changes to upstream

The [included patch](../resources/frame-controls.patch) includes these controls and menu changes:

1. It sets **LB = change grenade** and **RB = flashlight**. The pinned upstream branch assigns those two bumpers the other way around.
2. Before a weapon is equipped, the unarmed/default reticle follows the aiming hand. Look at the first mission's technician with your headset. The five calibration dots also recognize pointing with the hand reticle, using the original five-degree target cone. Cryopod look calibration accepts physical headset movement and legitimate snap/smooth stick turns, while ignoring tracking jitter and recenter/menu/cinematic transitions. Follow the technician's instructions and look up, down, left or right as requested. These tutorial inputs do not add head rotation to the equipped weapon's aim or change the campaign difficulty.
3. On foot, left-stick movement follows the headset's horizontal heading while your weapon still follows the controllers. Tracking loss suppresses walking instead of producing arbitrary movement. Vehicle controls keep their existing direction. Set `vr.movement = "aim"` (or `HALO_VR_MOVEMENT=aim`) to restore aim-relative movement; the installer defaults to `vr.movement = "head"`.

4. **Multiplayer > CO-OP CAMPAIGN** offers **HOST LOCAL (LAN)**, **JOIN LOCAL (LAN)**, **HOST ONLINE (INTERNET)**, **JOIN ONLINE (INTERNET)**, and **JOIN INVITE LINK**. Choose a host route, then campaign level and difficulty. Your friend uses the corresponding join route. Online hosting stays private by default; **LISTING = PUBLIC** allows server-browser joining by anyone. Each machine has one campaign player in VR and flat mode; campaign has no second-controller or split-screen option. See the [co-op setup guide](SETUP.md#online-campaign-co-op-with-a-friend).

The game's Steam shortcut also suppresses Steam's duplicate virtual Xbox gamepad with `SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0`. Frame controller poses, buttons and haptics still use OpenXR. This setting applies only to this Halo shortcut.

## First launch

Keep Steam Home and the headset runtime awake during setup. Launch **Halo: Combat Evolved VR (Native)** from the Frame's library. 1.4.1 keeps existing 1.4.0 profiles and saves in `~/Games/HaloCENativeVR/save-v1.4`. When upgrading from 1.3.5, create a new profile and campaign because its old checkpoints are incompatible and setup does not migrate those profiles. Use the d-pad to select menu items and **A** to accept. Keep the headset on and hold both grips if the menu appears outside your view.

For a control issue, first check **Settings > Gamepads** for a changed profile layout. Then check **Settings > VR Setup**: this layout uses controller aiming. Upstream also offers gamepad aiming, which moves aim with the right stick and has different camera behavior.

The original controls and all VR configuration options are documented in the [pinned upstream VR guide](https://github.com/startupfoundry/halo-ce-universal/blob/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/port/linux/README.md#vr). The [SDL hint source](https://github.com/libsdl-org/SDL/blob/release-3.4.16/include/SDL3/SDL_hints.h) documents virtual-gamepad filtering.
