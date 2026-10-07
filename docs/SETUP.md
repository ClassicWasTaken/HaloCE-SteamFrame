# Halo CE Steam Frame VR mod — setup 1.4.3

[Back to the project README](../README.md)

1.4.3 lets you select **Internal storage or SD card** for Install, Repair and Uninstall. Internal installs stay at `~/Games/HaloCENativeVR` with **Halo: Combat Evolved VR (Native)**. SD installs use the selected card's `Games/HaloCENativeVR` and **Halo: Combat Evolved VR (Native, SD card)**, keeping the internal copy. Existing 1.4.x saves at the selected location remain in `save-v1.4`; a new SD installation starts separate profiles/campaign saves. A 1.3.5 upgrade retains old saves but needs a new profile/campaign.

## Before you begin

Download and run the single [**Halo-Steam-Frame-Mod-Setup-1.4.3.exe**](https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/download/v1.4.3/Halo-Steam-Frame-Mod-Setup-1.4.3.exe) for Windows 10/11 x64. It includes its runtime and USB transfer tools; no administrator rights, Python installation, installer ZIP, or separate Platform Tools download is needed. Check its SHA256 on the [release page](https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/tag/v1.4.3) and follow [Verify release provenance](BUILD_PROVENANCE.md).

Use your own authorized original Xbox Halo CE ISO/XISO or extracted maps. USA Rev 2 was validated with the stable installer; the supported-build table below explains other retail revisions. Halo PC, Xbox 360 Anniversary, MCC, and Quest packages are unsupported. No retail game executable, disc image, maps, product keys, or soundtrack is bundled or downloaded. The project provides no game-download sources.

Halo artwork and trademarks remain copyrighted to their respective owners, and third-party software retains its licenses and notices. This community project is unaffiliated with Microsoft, Xbox, Bungie, or Valve. Its license does not grant rights in retail game data or certify the legal status of upstream source; see [third-party notices](THIRD_PARTY.md).

The Frame needs ARM64 SteamOS, SteamVR/OpenXR, rootless Podman, internet access, and **12 GiB free on the selected storage**. Setup checks these before installing. Your Windows computer needs about 2.5 GB of temporary space for maps. The SteamOS root filesystem stays read-only. Podman runs as the ordinary `steamos` host user; dependency installation uses root only inside the rootless container, with `no-new-privileges` retained.

The user confirmed that the private 1.4.3 candidate works on their Frame. Earlier reports also confirmed SD installation, menu placement and LAN/online campaign co-op. Automated checks cover the new controls, tracking and renderer guards; no measured FPS gain, frame-timing results or complete hardware/network test matrix is claimed.

The executable uses the classic Halo PC Master Chief helmet-and-shoulders icon. Its [source and hashes](../resources/ui/README.md) are documented separately from the installer's code license. The Steam library's project-drawn helmet icon is unchanged.

## Engine and save compatibility

The source is pinned to `2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4`. It includes upstream network campaign co-op, delayed texture-stage binding, and vertex clip-position handling changes. These renderer changes are a candidate improvement; they do not establish the cause or resolution of reported white flashes or frame drops.

1.4.3 uses **`~/Games/HaloCENativeVR`** and the Steam title **Halo: Combat Evolved VR (Native)**. It keeps the 1.4.0 save format and **`~/Games/HaloCENativeVR/save-v1.4`**; existing 1.4.x profiles and checkpoints do not require migration. Old 1.3.5 saves remain unchanged in their original `save` folder or configured location. The original config and program files are backed up in the owned installer run's `previous-program-files` folder. The 1.4 engine's larger game-state capacity makes 1.3.5 checkpoints incompatible. When upgrading from 1.3.5, create a new profile and campaign; setup does not automatically migrate those checkpoints or profiles.

Existing 1.4.0a2–a5 installations at `~/Games/HaloCENativeVRExperimental`, with the Steam title **Halo: Combat Evolved VR (Experimental)**, remain untouched. You can keep that tested copy for reference. The public 1.4.3 installer targets the internal or SD location you select.

With `vr.aim = "controller"`, **`vr.movement = "head"`** makes the left stick follow the headset's horizontal facing on foot. The right controller still aims the weapon. `vr.movement = "aim"` restores the previous aim-directed movement; `HALO_VR_MOVEMENT=aim` is the equivalent environment override. The movement patch excludes menus, flat mode, gamepad aiming, cinematics, remote players, and vehicle steering. Invalid tracking pauses head-directed movement rather than using an untrusted direction. The Xbox bumper layout and physical-head tutorial tests remain included.

**Multiplayer > CO-OP CAMPAIGN** opens network campaign choices in VR and flat mode: **HOST LOCAL (LAN)**, **JOIN LOCAL (LAN)**, **HOST ONLINE (INTERNET)**, **JOIN ONLINE (INTERNET)**, and **JOIN INVITE LINK**. Campaign uses one local player per machine; there is no second-controller or split-screen campaign route. Hosts start with **SINGLEPLAYER** maps selected. All peers need compatible **protocol 17** builds, matching game data and capacity limits; stable protocol 11 and retail Xbox/PC/Custom Edition/MCC clients cannot join. Extra co-op enemies default to `"none"`; Repair preserves a configured enemy mode.

The build stages `brokers.txt` for internet invite/server discovery. The relative default `network.brokers_file = "brokers.txt"` resolves beside the game's config; a custom setting is preserved. The tester confirmed LAN and online campaign work; successful joining still depends on compatible peers, reachable brokers, and each network's connectivity. [Pinned co-op implementation and protocol sources](SOURCES.md#140-engine-changes) explain these requirements.

## Online campaign co-op with a friend

Both players should use **the same 1.4.3 build** and supply their own supported original Xbox game data. Each player runs the game on their own headset or computer; campaign has one local player per machine. Use the left d-pad to navigate rows and change left/right choices, **A** to accept, and **B** to go back.

1. **Host:** open **Multiplayer > CO-OP CAMPAIGN**. On the same network choose **HOST LOCAL (LAN)**; across different networks choose **HOST ONLINE (INTERNET)**. The Map screen starts on **SINGLEPLAYER**. Choose a campaign level and difficulty.
2. In **Server Setup**, set **MAXIMUM PLAYERS** to 2 for two players, then select **START GAME**. For online browser discovery, change **LISTING** to **PUBLIC**. **PUBLIC lets anyone see and join the game.** Online co-op starts **PRIVATE** by default; setup does not force public listing.
3. **Friend:** open **Multiplayer > CO-OP CAMPAIGN > JOIN LOCAL (LAN)** or **JOIN ONLINE (INTERNET)** to match the host. Choose **REFRESH** if needed, select the host's game and press **A**. When both names appear in the lobby, let the countdown finish or select **START NOW**. If joining a game already underway opens its preview, select **JOIN GAME**.

For invite-only play, keep **LISTING = PRIVATE**. When the host's **INVITE LINK** row shows a `halo://join/` link, select that row and press **A** to copy it. Share it yourself through an app on the host's Frame. The friend copies it onto **their Frame's clipboard**, opens **Multiplayer > CO-OP CAMPAIGN > JOIN INVITE LINK**, selects **PASTE LINK**, then selects the host's game. Returning to the game can also consume the clipboard invite automatically. The PC and Frame have separate clipboards. The invite becomes unusable after the hosting game quits; switching a public game to private makes a new invite.

If a public game is missing, check that internet play is enabled on both games and that both use at least one reachable common broker. The browser needs broker support for retained listings; the included list supplies the defaults. Repairs preserve custom network settings, so an existing `network.online = false` or `network.public_lobby = false` must be corrected. **Settings > Network Setup > INTERNET PLAY** can enable internet play; restart Halo afterward.

If a game is visible but joining says **FAILED**, check matching builds/maps first. Gameplay uses **direct UDP**, STUN, and optional UPnP; the MQTT brokers carry discovery/signaling, **not a gameplay relay**. Strict NAT or carrier-grade NAT can prevent a distant friend joining. Try hosting from the other network. If an accessible home router still blocks it, choose a fixed `network.tunnel_port` in that game's `config.toml`, restart Halo, and forward that **UDP** port to the Frame on that router. UPnP cannot bypass a second upstream NAT. The successful headset report does not specify distant-peer or restrictive-NAT test coverage. [Primary internet-play and menu sources](SOURCES.md#online-co-op-menu-and-connection).

## Install Halo VR

On **Connect Frame**, click **Refresh storage** or **Test connection**, then choose **Internal storage** or a detected **SD card** and check the displayed destination. This selection applies to Install, Repair and Uninstall. SD cards require a writable, executable **ext4 or f2fs** filesystem mounted by SteamOS and **12 GiB free**; setup does not format or mount cards. Game files, new saves, the build workspace and backups use the selected drive. Steam artwork and Notes stay in the active account on internal storage. Podman can still need internal space for its compiler container. [SD-card guide](SD_CARD.md).

Menus capture your current headset position and gaze when opened and stay level, even with your head tilted. They stay in place while open; close/reopen or recenter to place one in front again. Opening Pause hides gameplay hands, gun, reticle and zoom overlays while keeping the controller pointer and Xbox menu buttons available.

1. **Game data.** Choose **Install**. For a first installation, use **Choose ISO** or **Choose maps folder** to select an original **Xbox** Halo CE `.iso` / `.xiso`, or its extracted `maps` folder, that you are authorized to use. Setup validates the retail Xbox map format and extracts only the required maps. A recognized, verified 1.3.5 installation can reuse its Xbox maps without another ISO; see [upgrade instructions](#already-have-halo-installed). Halo PC, Xbox 360 Anniversary, MCC, and Quest packages are not inputs for this build. The repository and executable contain no commercial game data or download links for it. Click **Continue** to move to the next step.
2. **Connect Frame.** Enable Developer Mode and set the Frame's user password, then choose **Network (Wi-Fi or Ethernet)** or **USB-C cable**. For network transfer, keep both devices on a network that permits connections between them and enter the Frame's hostname/IP. For USB, connect a data-capable cable directly to the PC and approve device authorization on the headset if prompted; no Frame IP is required. The SSH login remains `steamos`, port 22; username and port are under **Advanced connection settings**. Click **Test connection** and approve the displayed host fingerprint only after identifying your device. Your password is used in memory and is never saved or logged.
3. **Install Halo VR.** Save and close games, confirm **I have saved and closed games on my Frame**, then click **Install Halo VR**. Keep Steam Home and SteamVR running, and leave the Frame awake and connected. The app uploads or verifies maps, creates a rootless build container, compiles the pinned VR source, applies the controls patch, and registers **Halo: Combat Evolved VR (Native)** through the running Steam client when its verified library interface is available. Any remaining shortcut or artwork step is shown at the end; it does not require rebuilding the game. The first build may take tens of minutes. Activity opens automatically and shows the current phase and live build output; use **Save log** for troubleshooting.

### Transfer over a USB-C cable

1. In the Frame's **Steam Settings > System**, enable **Developer Mode**. In **Developer**, set a user password. Leave Steam Home and SteamVR running.
2. Connect the Frame directly to your Windows PC with a USB data cable. A charging-only cable cannot transfer files. Keep the Frame awake and allow this computer's device authorization on the headset if prompted.
3. In **Connect Frame**, choose **USB-C cable**. **Advanced connection settings > Browse adb.exe** selects an explicit installation first. Otherwise setup uses its verified included ADB 37.0.1 files before SDK/PATH fallback. A damaged bundle is rejected. If you need replacement tools, use [Google's official Windows Platform Tools download and terms](https://developer.android.com/tools/releases/platform-tools), extract the complete package, and choose its `platform-tools\adb.exe`, keeping the companion DLLs next to it. Setup does not download SDK tools during an installation.
4. Enter the same Frame user password used for SSH and click **Test connection**. Setup selects the sole physical USB device automatically. If several physical USB devices are connected, unplug the others or enter the Frame's exact ADB serial in **Advanced connection settings**. If a serial cannot be verified as a physical USB connection, unplug other devices and leave the serial field blank for automatic detection. Emulators and network-connected ADB devices are not USB targets. Review the Frame's SSH host fingerprint when asked.
5. Continue with install, repair, library registration, or uninstall. Leave the cable attached until setup reports that it has disconnected. Setup removes only the temporary ADB forward it created and leaves the shared ADB server and other forwards running.

The cable carries encrypted SSH/SFTP traffic between the PC and Frame. **The Frame still needs its own internet connection** to fetch native source, the build container, and compiler dependencies. USB does not provide internet sharing or change Wi-Fi/Steam settings. Cable transfer may help on a weak or congested wireless network; actual speed depends on the cable, USB ports, and device. It does not speed up the native compilation phase. USB behavior has automated software coverage; physical Steam Frame USB transfer verification is pending. [Valve's USB/ADB guide](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging) and [Google's ADB reference](https://developer.android.com/tools/adb) describe the underlying connection and forwarding tools.

The installation bar fills from left to right and does not move backward during a run. Its overall percentage combines weighted stages with measured upload bytes and completed Ninja build tasks. During work without a measurable total, such as package setup or configuration, the bar holds its last value while the activity feed continues showing available output. This percentage describes completed work, not elapsed time or a finish-time estimate. Failure or cancellation preserves the reached progress. Pending Steam information, uninstall files, or connection cleanup stays at 99%, with the remaining action explained; only full success reaches 100%.

Setup closes its SFTP and command channels and the underlying SSH connection after each operation, including failure and cancellation. The activity feed shows disconnecting and disconnected stages when cleanup succeeds. A connection-cleanup failure is shown separately from the game result: an installed game remains installed, and a completed removal remains recorded. Follow the displayed connection-cleanup instructions before closing setup; a remaining cleanup step stays at 99%. USB cleanup removes only this operation's temporary ADB forward. Setup does not stop the shared ADB server or change the Frame's Wi-Fi or Steam streaming settings.

If a prepared build is cancelled, times out, or loses its connection, setup tries to stop that same installer run. If the existing stop request fails, it makes one bounded reconnect attempt using the SSH host key you already approved. It does not approve a different key. If the Frame cannot confirm stopping, setup warns that the build may still be running and provides the exact stop command for the Frame's terminal. Restore the connection and follow that command before retrying installation or uninstalling. A completed cancellation reports **Setup cancelled** without a failure dialog. Genuine failures, failed cleanup and unconfirmed remote stopping still require attention. SSH setup waits are bounded, and cancellation remains responsive during continuously streamed output.

The included ADB executable, two companion DLLs, and unmodified notices are checksum-verified before being copied to `%LOCALAPPDATA%/HaloFrameInstaller/usb-tools/37.0.1`. This versioned cache remains after setup closes so a shared ADB server can keep using it without locking the EXE's temporary extraction folder. The selected client's protocol is checked against an already-running local ADB server; a mismatch stops USB setup without restarting that server. Setup also verifies that the temporary forwarded port listens only on this PC's loopback addresses before sending the SSH password. [Bundled-tool provenance and licenses](THIRD_PARTY.md#adb-for-usb-transfer).

These changes apply after you launch the new EXE and start a run. An installation already running in an older EXE keeps its existing behavior; downloading a replacement cannot change that ongoing process.

After you select valid local Xbox game data, the installer automatically loops the original Halo menu music. Validation and music preparation run in the background. Setup reads the menu loop from your own `ui.map`, decodes it at 12% of the original sample amplitude, and keeps the temporary audio on your Windows computer until the installer closes. No soundtrack is bundled, downloaded, or uploaded to the Frame. Repair using only maps already on the Frame has no local music preview. If music is unavailable, installation can continue.

### Supported Xbox ISO revisions

Use **Halo: Combat Evolved for the original Xbox**. **USA Rev 2 was validated with the stable installer.** 1.4.3 retains its map-header checks. Other retail revisions, including an original USA release or an image labeled **USA Rev 1**, and PAL releases are accepted when their actual map headers match one of these supported builds:

| Map-header build | Upstream region |
| --- | --- |
| `01.10.12.2276` | NTSC |
| `01.08.15.1749` | NTSC |
| `01.01.14.2342` | PAL |

These builds come from the [pinned port's compatibility table](https://github.com/startupfoundry/halo-ce-universal/blob/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/source/cache/cache_files.c#L616-L631). Its [PAL conversion notes](https://github.com/startupfoundry/halo-ce-universal/blob/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/port/linux/game/pal_tags.c#L4-L22) describe the shared NTSC maps across three retail releases. Setup checks the image contents, not its filename or a Rev label: it requires all 24 original Xbox version-5 maps from one supported build. Incomplete or mixed-build sets and unlisted builds are rejected. Halo PC/Custom Edition, Xbox 360 Anniversary, MCC, and Quest packages are unsupported inputs. Supply your own authorized retail ISO/XISO or extracted maps.

### Already have Halo installed?

To update an existing installation, close **Halo: Combat Evolved VR (Native)** and choose **Repair**. Setup rebuilds the native program and applies the 1.4.3 patch, reusing verified Xbox maps without another ISO. Install also recognizes a verified 1.3.5 installation and upgrades its program in place. Setup replaces the native program, SDL library, broker list, patch, and notices. If maps are missing or damaged, select valid local data and retry. An unknown folder can be adopted only through explicit Repair after its native executable and Xbox maps validate; other locations are left alone.

The update keeps existing 1.4.x profiles/checkpoints in `save-v1.4` and backs up the original config and program in the owned build run's `previous-program-files` folder. Upgrading from 1.3.5 retains its old saves at their original location and selects `save-v1.4` for a new profile/campaign; there is no automatic migration of 1.3.5 checkpoints or profiles. Repairs keep unrelated settings. A failed replacement rolls back affected program/config files while the selected mount remains valid. If an SD card changes, setup stops and keeps its original backups rather than restoring onto another mount. The separate 1.4.0a2–a5 Experimental copy is not removed or upgraded by this installer.

An interrupted 1.3.5 upgrade can be recovered when setup verifies the original owned cache, program/config backups and installed replacements. Keep the game folder and installer cache, then retry Install or Repair. Recovery preserves both save generations and recorded custom save locations. Missing, changed or ambiguous evidence is refused with a preservation message; some older repeated interruptions still need manual recovery. Malformed configuration is also rejected without resetting preferences or save paths.

The old PC installation at `~/Games/HaloCEVR` is detected and explained separately. Its PC maps cannot be used for this native Xbox build. Setup installs the native version separately and does not automatically remove the PC version. Close the native game before repair. Program-file backups are retained in the owned build workspace, and a failed repair rolls back the affected files. **Add to Steam again** repairs library registration and adds missing library artwork; it does not rebuild the game.

With Steam running, setup uses the current client's library interface and verifies the native executable, launch options, VR flag, and disabled compatibility tool before reporting registration success. This interface is undocumented and may change with Steam updates. If it is unavailable, ambiguous, or cannot verify the result within its time limit, setup keeps the headset session running and shows manual steps. Use Steam's **Add a Game > Add a Non-Steam Game** to select the executable path shown by setup (`~/Games/HaloCENativeVR/halo` for internal storage, or the selected card's `Games/HaloCENativeVR/halo`), apply the launch option below, and enable **Include in VR Library**. Leave forced compatibility tools disabled for this native Linux executable. **Add to Steam again** retries available library setup without rebuilding. If Steam is already closed, setup can use backed-up atomic library-file updates; it never shuts down, launches, or restarts the headset's Steam session.

### Automatic Steam library information

Install and Repair automatically update the native Steam shortcut, missing artwork, and **Halo CE VR — About & controls** note after the game is ready. The note includes online hosting/joining instructions. Only exact unchanged earlier installer notes are upgraded; edited or unfamiliar notes remain untouched. There is no separate Steam info option to select. Save and close games, leave Steam Home running, and keep the headset connected until setup disconnects. If registration, artwork, or Notes remains pending at the end, **Add to Steam again** retries that step without transferring maps or rebuilding the game.

Open **Notes** on the Halo game's Steam details page or in its overlay to read the description and control guide. These are private game notes using Steam's normal notes synchronization. They do not replace the non-Steam About panel or add a store page, achievements, reviews, or another game's Steam identity. Existing notes and edited installer notes remain unchanged. If Notes is unavailable or synchronization cannot be verified, setup shows copyable text for manual use. Missing artwork or an icon awaiting Steam's shortcut-file persistence is reported separately and can be retried with **Add to Steam again**. Notes requires a running, verified Steam client; setup leaves a closed Steam client closed.

### Uninstall Halo VR

Choose **Uninstall** on the first page, then select **Internal storage** or the detected **SD card** on Connect Frame. Setup removes only that location's recognized native installation and exact Steam shortcut. You do not need an ISO or local maps for uninstall, but you must connect over SSH with the Frame's user password. Save and close games; keep Steam Home and SteamVR running. Setup matches native shortcuts by their exact executable, so renaming the entry in Steam does not prevent removal. It verifies shortcut removal before deleting game files. If the client interface is unavailable or removal cannot be verified, setup keeps the native game files and stops at 99%, explaining Steam's **Remove Non-Steam Game** option. Invalid matching shortcut records also stop removal before library-file changes. An owned installation build still running stops removal before deletion. Setup never shuts down or relaunches Steam. If Steam is already closed, automatic removal can use its backed-up library-file path across the local accounts.

**Keep my campaign saves in a backup (recommended)** is checked by default. Setup backs up recognized saves inside the selected native game folder, including retained `save` and active `save-v1.4` data, together with the game's config to `Games/HaloCENativeVR-saves-<operation ID>` beside that game on the same drive. It reports the exact backup location. The recognized native folder, including its maps, program files, and config, is then removed; configured saves outside that folder remain untouched. Turning off the checkbox allows saves inside the removed folder to be deleted. Uninstall leaves the other drive's installation, unrelated games, foreign or unrecognized folders, and unrelated settings alone. The build cache remains available for troubleshooting. Setup disconnects its SSH session after the operation and reaches 100% only after completion.

If an earlier uninstall was interrupted, run **Uninstall** again. Setup can finish deleting its verified unfinished game folders even when the main game folder is gone or Halo has since been reinstalled. It checks the earlier operation's private record and the remaining folder's identity before resuming. Verified save backups remain in place, and their paths appear in the result. Changed or unverified folders are preserved and listed for review; setup reports removal pending at 99% instead of claiming the game was already absent. Review **Show activity** and **Save log** for these paths. Do not delete a reported save backup. If setup reports that it reached its recovery limit, run Uninstall again to continue; folders that fail verification need manual review.

With the client running, Steam controls artwork cleanup for the removed entry; setup does not delete its live grid files. With Steam already closed, setup removes only artwork matching the installer's known image hashes and preserves custom images.

## Xbox-style controls

On foot and in menus:

| Frame control | Action |
| --- | --- |
| A | Jump / accept |
| B | Melee / back |
| X | Reload / use |
| Y | Change weapon |
| Right trigger / left trigger | Fire / throw grenade |
| Left stick / click | Move / crouch |
| Right stick / click | Turn / zoom |
| Left bumper / right bumper | Change grenade / flashlight |
| Menu / View | Pause / scoreboard |
| Both grips held | Recenter outside driver seats |

Install and Repair apply motion aiming, standing mode, snap turning and physical punch-to-melee. Fresh installs use 30-degree snap turns, 72 Hz and render scale 1.0. Repairs keep other settings and saves. **Pause > VR Setup** opens Controls and Display options. Weapons use Halo's original zoom and direct controller aiming; the experimental gun-mounted scope and custom zoom smoothing are removed.

In the **Warthog driver's seat**, hold **A for gas**, hold **B to brake**, and steer with left-stick left/right. Left-stick backward reverses; B takes priority over gas and reverse. Both grips engage an optional two-hand wheel; release either grip to return to the stick. Release A and both grips once after boarding, a menu or tracking loss. Seated views capture a forward-facing reference and follow the vehicle's full tilt and bounce; hold View/Back for one second to recenter after sitting down. See [all vehicle controls](CONTROLS.md#vehicles).

Valid controller poses continue aiming outside the headset's view. Missing right-controller tracking hides the gameplay rig and reticle; missing left-controller tracking hides only that hand. Tracking loss does not create centered HUD aim. Head movement and deliberate stick turns satisfy the first-level look tutorial; the calibration dots also accept the unarmed hand reticle. Campaign difficulty is unchanged.

The native shortcut uses this **per-game** launch option to prevent the same physical controller from being read through both OpenXR and Steam's virtual gamepad:

```text
SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0 %command%
```

See [controls and patch details](CONTROLS.md).

## What gets installed

Game: `~/Games/HaloCENativeVR`, including `halo`, bundled SDL3, your maps, config, notices, and an ownership/provenance manifest. New engine saves use `save-v1.4`; old 1.3.5 saves stay in `save` or their original configured location. Build workspace: `~/.cache/halo-frame-installer`; previous program/config backups are retained inside the owned installer run's `previous-program-files` folder. Windows installer state uses `%LOCALAPPDATA%/HaloFrameInstaller`. Source is fetched at the fixed commit below, not a moving branch. Build cache is retained for troubleshooting. Setup replaces the recognized 1.3.5 native program and leaves other Halo installations and unrelated games alone.

The original Halo CE cover is shown inside the installer. The native shortcut receives missing portrait and landscape covers, a 1,920 × 620 original CE promotional banner, transparent title logo, and the project-drawn Master Chief helmet icon. With Steam running, setup uses its verified client interface, checks the active account and native executable, and verifies the artwork hashes. The icon is kept in the owned game's `.installer-artwork` folder so it survives the setup EXE closing. Its existing path is verified through read-only shortcut-file checks before changing it through Steam's API. Both running-client and already-closed file paths preserve custom art and icons, including different supported image extensions. An icon that cannot be verified is left unchanged and recorded in Show activity. This optional icon does not block completion: successful Install and Repair show Complete at 100%.

The description and Xbox controls use **Steam Game Notes**. Setup appends one bounded note without replacing other notes or an edited installer note. Artwork and Notes have independent pending states; Install, Repair, and any completion retry use the same handling. No artwork download is needed. The bundled images total less than 1 MB, with sources and exact hashes in the [artwork resource notice](../resources/artwork/README.md). The user confirmed the entry and covers on the Frame tested with 1.2.3. Banner, logo, icon, and Notes integration also have automated coverage.

The renderer uses the Xbox game's data and translated Xbox shaders. Native OpenXR VR and competitive multiplayer come from the port. The PC-only Chimera, PC Restored maps, and HaloCEVR DLLs do not belong in this native build. Multiplayer requires compatible native/OpenCE protocol builds; Halo PC/Custom Edition/MCC servers and PC save files are incompatible.

## Sources and credits

- [OpenCE Steam Frame VR PR #85](https://github.com/OpenCommunityEdition/OpenCE/pull/85), by startupfoundry.
- [Exact VR source commit `2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4`](https://github.com/startupfoundry/halo-ce-universal/tree/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4), with a documented local controller/tutorial patch.
- [astromaddie/HaloCE-VR](https://github.com/astromaddie/HaloCE-VR/tree/cff675537d961051d4aaf016c1e437542420b7df), for the menu, radar and optional buffer-streaming adaptation references credited in [SOURCES.md](SOURCES.md#143-vr-refinements).
- [Upstream native Linux/VR build instructions](https://github.com/startupfoundry/halo-ce-universal/blob/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/port/linux/README.md#vr).
- [Valve's official Frame setup](https://partner.steamgames.com/doc/steamhardware/steamframe/setup) and [SSH/debugging instructions](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging).
- [Google's ADB connection and forwarding reference](https://developer.android.com/tools/adb) and [official Platform Tools download and terms](https://developer.android.com/tools/releases/platform-tools).
- [Original Xbox dashboard visual references](SOURCES.md#dashboard-visual-references) and [Halo CE artwork attribution and Steam Notes references](SOURCES.md#steam-library-artwork).
- [Dime (dime-online)](https://github.com/dime-online), for the 1.4.2 installer fixes credited in the [release notes](RELEASE_NOTES.md).

Full source attribution, decompilation lineage, multiplayer references, and third-party licenses are in [SOURCES.md](SOURCES.md) and [THIRD_PARTY.md](THIRD_PARTY.md). Original installer code is MIT licensed. Upstream notices apply separately; no license here grants rights to commercial game data.

## Troubleshooting

- **Cannot resolve `frame`:** for Wi-Fi / Ethernet, use the Frame's IP address from its network settings. Both devices must be on a network that permits connections between clients. USB-C transfer does not need the hostname/IP.
- **USB device missing or offline:** verify Developer Mode, keep the Frame awake, use a data-capable cable and a direct PC USB port, and reconnect it. A charging indicator alone does not confirm data transfer. Approve device authorization on the headset if prompted. Setup does not reset shared ADB services or change device settings automatically.
- **Several USB devices detected:** unplug other physical USB devices or enter the Frame's exact ADB serial in **Advanced connection settings**. Setup refuses to guess which device to use. If that serial's physical USB path cannot be verified, leave it blank with only the Frame attached and retry automatic detection.
- **ADB unavailable:** the release EXE includes ADB. If its files cannot be used, extract [Google's official Windows Platform Tools package](https://developer.android.com/tools/releases/platform-tools), keeping `adb.exe` and its companion DLLs together, then choose it with **Browse adb.exe**. Wi-Fi / Ethernet remains available without ADB.
- **ADB server version differs:** setup leaves that server running. Choose the matching `adb.exe` under **Advanced connection settings**, or close the other application's USB tools normally and retry. Network transfer remains available.
- **USB forwarding has network access enabled:** setup refuses to send the SSH password over a forward listening beyond loopback. Close the other application's USB tools normally and retry, or choose network transfer. Setup does not reset the shared server automatically.
- **USB SSH connection refused:** enable Developer Mode and confirm the SSH port in **Advanced connection settings**. USB still needs the Frame's SSH service and user password; ADB authorization alone does not authenticate SSH. The USB path forwards the Frame's default SSH port 22.
- **Connection refused:** enable Developer Mode and verify the address and SSH port. [Valve guide](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging).
- **Authentication fails:** enter the password set in the Frame's Developer settings; your Steam account password is unrelated.
- **Host key changed:** setup refuses the connection. Verify the new device/key independently before removing its old public fingerprint from `%LOCALAPPDATA%/HaloFrameInstaller/hosts.json`.
- **Insufficient disk space or Podman missing:** resolve the failed preflight check and retry. Setup does not disable SteamOS protections or install system packages as root.
- **SD card missing or changed:** insert the same prepared card, click **Refresh storage**, and check the selected destination before retrying. Setup rejects unmounted, read-only, non-executable or unsupported filesystems. It does not move the game to internal storage. Keep the card inserted while launching or playing its SD installation. [SD-card guide](SD_CARD.md).
- **Build/download fails:** the error dialog shows a short failure headline; open **Show activity** or **Save log** for the full redacted details. Keep the Frame's build log and retry. Version 1.2.1 fixes the container dependency-installation permission errors (`setgroups`, `seteuid`, or APT cache permissions) seen in 1.2.0. Retry can reuse previously uploaded maps only when the complete map set matches the selected local data manifest and passes header and SHA256 verification; otherwise setup uploads fresh data. Reused data stays in its previous owned upload run and is verified again at build and finalization. A failed staging build does not replace an existing game or save.
- **Cancelled, but remote stopping is unconfirmed:** the build may still be running. Restore the connection and run the exact stop command shown by setup in the Frame's terminal before installing or uninstalling again. Setup's recovery connection accepts only your previously approved host key.
- **Game operation finished, connection cleanup pending:** follow the separate cleanup warning and save the activity log. The game outcome is retained; a USB-forward cleanup error does not undo an installation or completed uninstall. Setup leaves the shared ADB server and unrelated forwards alone.
- **Uninstall interrupted or folders preserved:** run Uninstall again to finish verified leftovers. Save backups remain separate and their verified paths are reported. If files cannot be verified, setup lists the preserved folders and remains at 99%; review the log before any manual removal. An invalid matching Steam shortcut must be corrected in Steam before retrying uninstall.
- **Unsupported ISO or maps:** choose original Xbox retail data matching a [supported map build](#supported-xbox-iso-revisions). USA Rev 2 is validated; a filename containing Rev 1 or Rev 2 does not establish compatibility by itself. Keep all required maps from one release together.
- **Frame slept during compilation:** reconnect, wake the Frame and keep it awake before retrying. Setup requests a temporary sleep inhibitor during the build and refuses to start a second installer build while the earlier container is still running. If stopping cannot be verified, follow the displayed recovery command first.
- **Flat window instead of VR:** wake the headset and start SteamVR before launching. The port falls back to a flat window if no usable OpenXR session is available.
- **Controls doubled:** check the native shortcut's launch option above. Steam Input may otherwise add a second virtual controller stream.
- **Library entry absent:** click **Add to Steam again** to retry registration through the running client. If its library interface remains unavailable, use Steam's **Add a Non-Steam Game** with the executable and launch option above. Enable **Include in VR Library** and leave forced compatibility tools disabled in its properties. Setup's direct library-file edits require Steam to be already closed.
- **Artwork or description absent:** Install and Repair add these automatically. If setup reports pending Steam information, click **Add to Steam again** after the run. The description is under **Notes**, not the non-Steam About panel. Pending artwork or Notes is reported separately from the shortcut; manual Notes includes copyable text. Optional shortcut-icon details stay in the activity log. Existing custom artwork and notes are kept. Direct file edits require Steam to be already closed; Notes needs the running client's interface.
- **Steam Home remains on a loading logo after an older installer run:** 1.2.3 removes the automatic shutdown request that disrupted the SteamOS-managed session in a reported case. It does not repair a session already in a failed state. Restart the Frame using its normal power controls, and contact Steam Support if Steam Home does not return. [Steam session safeguard and diagnostic sources](SOURCES.md#steam-session-safeguard).
- **Menu music unavailable:** select valid local original Xbox data containing `ui.map`; music starts automatically after validation. A repair using only remote maps cannot preview music. Playback errors do not block setup; Windows volume controls the final sound level.

The executable is unsigned. Follow [Verify release provenance](BUILD_PROVENANCE.md) to check the downloaded artifact and its build source; this project does not ask you to disable antivirus or other security protections. Review logs for private information before sharing them.

## Develop and rebuild the executable

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m halo_frame_installer
.\.venv\Scripts\python scripts/build_release.py
```

The build writes a matching installer source bundle and `SHA256SUMS.txt` to `dist/` alongside the EXE. These remain local build outputs. The public release uploads one EXE and lists its SHA256 in the release notes; matching installer source is available in the [v1.4.3 Git tag](https://github.com/ClassicWasTaken/HaloSteamFrameMod/tree/v1.4.3), with GitHub's automatic source downloads available for developers. Applicable third-party source/notices are included for rebuilding, including the LGPL Paramiko dependency. ADB binaries are not checked into Git; [bundle_usb_tools.py](../scripts/bundle_usb_tools.py) downloads the pinned official archive during the executable build and verifies its archive and selected-file checksums before packaging. [resources/usb/manifest.json](../resources/usb/manifest.json) records those hashes and provenance. The package contains installer code/resources and verified tools with their notices; no retail executable, ISO, maps, SSH password, or private key is included.

To check an exact local engine checkout without connecting a headset or downloading data, run `python scripts/check-experimental-engine.py PATH_TO_ENGINE_CHECKOUT`. The checker accepts a clean or fully patched checkout at the pinned revision, checks patch applicability in a private temporary projection, and verifies renderer/co-op/protocol/control integration. It generates the ARM64 Ninja graph offline with external downloads disabled; this is a source/configuration check, not an ARM64 compilation or headset test.

The workflow also includes an ARM64 Linux check, [check-build-container.py](../scripts/check-build-container.py), that uses the same rootless Podman arguments as the Frame build. It checks APT package installation, `setgroups`, `seteuid`, `setegid`, `chown`, and that container output belongs to the ordinary host user. The Windows executable CI job depends on that check as well as the unit tests. This container check uses no game data and does not replace a full Steam Frame installation test.

Before reporting a hardware test, record the SteamOS/SteamVR version, source commit, install status, and whether menu, campaign, Xbox controls, tutorial, and compatible multiplayer worked. Do not attach game data or credentials.
