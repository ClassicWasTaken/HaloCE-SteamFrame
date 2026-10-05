# Steam Frame controls

The default installation uses tracked controller aiming with Xbox-style buttons. Point the right controller to aim; move your head to look around. These controls assume the game's default profile button layout.

| Frame input | Action |
| --- | --- |
| Left stick | Move |
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

## Local changes to upstream

The [included patch](../resources/frame-controls.patch) makes two changes:

1. It sets **LB = change grenade** and **RB = flashlight**. The pinned upstream branch assigns those two bumpers the other way around.
2. Physical headset movement counts toward the campaign's look-direction tutorial while motion-controller aiming is active. Follow the technician's instructions and physically look up, down, left or right as requested. The patch ignores small tracking jitter and does not add head rotation to the weapon's aim. It lets the tutorial complete at the selected difficulty; it does not skip the campaign or raise its difficulty.

The game's Steam shortcut also suppresses Steam's duplicate virtual Xbox gamepad with `SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0`. Frame controller poses, buttons and haptics still use OpenXR. This setting applies only to this Halo shortcut.

## First launch

Keep Steam Home and the headset runtime awake during setup. Launch **Halo: Combat Evolved VR (Native)** from the Frame's library and create a profile. Use the d-pad to select menu items and **A** to accept. Keep the headset on and hold both grips if the menu appears outside your view.

For a control issue, first check **Settings > Gamepads** for a changed profile layout. Then check **Settings > VR Setup**: this layout uses controller aiming. Upstream also offers gamepad aiming, which moves aim with the right stick and has different camera behavior.

The original controls and all VR configuration options are documented in the [pinned upstream VR guide](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/linux/README.md#vr). The [SDL hint source](https://github.com/libsdl-org/SDL/blob/release-3.4.16/include/SDL3/SDL_hints.h) documents virtual-gamepad filtering.
