# Steam Frame controls — 1.4.0

1.4.0 uses head-directed walking and tracked controller aiming with Xbox-style buttons. Point the right controller to aim; the left stick moves relative to the horizontal direction of your headset. These controls assume the game's default profile button layout.

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

The installer defaults to controller aiming, seated height, 72 Hz, resolution scale 1.0, smooth turning at 90 degrees per second, and two-handed aiming. Gesture melee is disabled so **B** remains the predictable melee input. These are installer preferences, not the upstream defaults. You can change supported options in **Settings > VR Setup** or the game's `config.toml`. Choose snap turning in VR Setup if you prefer turning in steps. Some display changes require restarting the game.

The reticle previews the nominal primary shot using Halo's firing calculation and projectile collision mask. On foot it uses render-frame aim, so its direction is no longer limited to the unit's 30 Hz updates; the hit is traced anew each frame. The headset tester confirmed the updated reticle motion works. Random spread and ballistic motion can still move individual impacts away from that point. Stereo sun glow defaults to `vr.sun_glow_strength = 0.5` in `config.toml`; 0 disables its glow, and 1 restores full intensity. Repair preserves a custom value.

## Local changes to upstream

The [included patch](../resources/frame-controls.patch) includes these controls and menu changes:

1. It sets **LB = change grenade** and **RB = flashlight**. The pinned upstream branch assigns those two bumpers the other way around.
2. Physical headset movement counts toward the campaign's look-direction tutorial while motion-controller aiming is active. Follow the technician's instructions and physically look up, down, left or right as requested. The patch ignores small tracking jitter and does not add head rotation to the weapon's aim. It lets the tutorial complete at the selected difficulty; it does not skip the campaign or raise its difficulty.
3. On foot, left-stick movement follows the headset's horizontal heading while your weapon still follows the controllers. Tracking loss suppresses walking instead of producing arbitrary movement. Vehicle controls keep their existing direction. Set `vr.movement = "aim"` (or `HALO_VR_MOVEMENT=aim`) to restore aim-relative movement; the installer defaults to `vr.movement = "head"`.

4. **Multiplayer > CO-OP CAMPAIGN** offers **HOST LOCAL (LAN)**, **JOIN LOCAL (LAN)**, **HOST ONLINE (INTERNET)**, **JOIN ONLINE (INTERNET)**, and **JOIN INVITE LINK**. Choose a host route, then campaign level and difficulty. Your friend uses the corresponding join route. Online hosting stays private by default; **LISTING = PUBLIC** allows server-browser joining by anyone. Each machine has one campaign player in VR and flat mode; campaign has no second-controller or split-screen option. See the [co-op setup guide](SETUP.md#online-campaign-co-op-with-a-friend).

The game's Steam shortcut also suppresses Steam's duplicate virtual Xbox gamepad with `SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0`. Frame controller poses, buttons and haptics still use OpenXR. This setting applies only to this Halo shortcut.

## First launch

Keep Steam Home and the headset runtime awake during setup. Launch **Halo: Combat Evolved VR (Native)** from the Frame's library. 1.4.0 replaces the 1.3.5 program while retaining its old saves unchanged. The new engine uses `~/Games/HaloCENativeVR/save-v1.4`; create a new profile and campaign because old checkpoints are incompatible and setup does not migrate profiles. Use the d-pad to select menu items and **A** to accept. Keep the headset on and hold both grips if the menu appears outside your view.

For a control issue, first check **Settings > Gamepads** for a changed profile layout. Then check **Settings > VR Setup**: this layout uses controller aiming. Upstream also offers gamepad aiming, which moves aim with the right stick and has different camera behavior.

The original controls and all VR configuration options are documented in the [pinned upstream VR guide](https://github.com/startupfoundry/halo-ce-universal/blob/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/port/linux/README.md#vr). The [SDL hint source](https://github.com/libsdl-org/SDL/blob/release-3.4.16/include/SDL3/SDL_hints.h) documents virtual-gamepad filtering.
