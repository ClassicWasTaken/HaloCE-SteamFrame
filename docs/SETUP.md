# Halo CE Steam Frame VR mod setup

[Back to the project README](../README.md)

This community VR mod installer guides you through installing the experimental native Halo CE VR port. This guide covers USB-C and network connections, repair, Steam library updates, removal, troubleshooting, and rebuilding the Windows executable.

## Before you begin

Download the single **[Halo-Steam-Frame-Mod-Setup-1.3.4.exe](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/releases/download/v1.3.4/Halo-Steam-Frame-Mod-Setup-1.3.4.exe)** for Windows 10/11 x64. It includes its runtime and USB transfer tools; no administrator rights, Python installation, installer ZIP, or separate Platform Tools download is needed. The [release notes](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/releases/tag/v1.3.4) include the EXE's SHA256 checksum.

Use your own authorized original Xbox Halo CE ISO/XISO or extracted maps. USA Rev 2 is validated; the supported-build table below explains other retail revisions. Halo PC, Xbox 360 Anniversary, MCC, and Quest packages are unsupported. No retail game executable, disc image, maps, product keys, or soundtrack is bundled or downloaded. The project provides no game-download sources.

Halo artwork and trademarks remain copyrighted to their respective owners, and third-party software retains its licenses and notices. This community project is unaffiliated with Microsoft, Xbox, Bungie, or Valve. Its license does not grant rights in retail game data or certify the legal status of upstream source; see [third-party notices](THIRD_PARTY.md).

The Frame needs ARM64 SteamOS, SteamVR/OpenXR, rootless Podman, internet access, and **12 GiB of free internal storage**. Setup checks these before installing. Your Windows computer needs about 2.5 GB of temporary space for maps. The SteamOS root filesystem stays read-only. Podman runs as the ordinary `steamos` host user; dependency installation uses root only inside the rootless container, with `no-new-privileges` retained.

The native game, Xbox controls, and older Steam shortcut/covers were previously tested on a physical Frame. USB transfer, a complete fresh-device install/uninstall, and the newer banner/logo/icon/Notes still need hardware verification. The upstream VR implementation is experimental, and performance varies by scene and device.

The executable uses the classic Halo PC Master Chief helmet-and-shoulders icon. Its [source and hashes](../resources/ui/README.md) are documented separately from the installer's code license. The Steam library's project-drawn helmet icon is unchanged.

## Install Halo VR

1. **Game data.** Choose **Install**, then use **Choose ISO** or **Choose maps folder** to select an original **Xbox** Halo CE `.iso` / `.xiso`, or its extracted `maps` folder, that you are authorized to use. Setup validates the retail Xbox map format and extracts only the required maps. Halo PC, Xbox 360 Anniversary, MCC, and Quest packages are not inputs for this build. The repository and executable contain no commercial game data or download links for it. Click **Continue** to move to the next step.
2. **Connect Frame.** Enable Developer Mode and set the Frame's user password, then choose **Network (Wi-Fi or Ethernet)** or **USB-C cable**. For network transfer, keep both devices on a network that permits connections between them and enter the Frame's hostname/IP. For USB, connect a data-capable cable directly to the PC and approve device authorization on the headset if prompted; no Frame IP is required. The SSH login remains `steamos`, port 22; username and port are under **Advanced connection settings**. Click **Test connection** and approve the displayed host fingerprint only after identifying your device. Your password is used in memory and is never saved or logged.
3. **Install Halo VR.** Save and close games, confirm **I have saved and closed games on my Frame**, then click **Install Halo VR**. Keep Steam Home and SteamVR running, and leave the Frame awake and connected. The app uploads maps, creates a rootless build container, compiles the pinned VR source, applies the controls patch, and registers **Halo: Combat Evolved VR (Native)** through the running Steam client when its verified library interface is available. Any remaining shortcut or artwork step is shown at the end; it does not require rebuilding the game. The first build may take tens of minutes. Activity opens automatically and shows the current phase and live build output; use **Save log** for troubleshooting.

### Transfer over a USB-C cable

1. In the Frame's **Steam Settings > System**, enable **Developer Mode**. In **Developer**, set a user password. Leave Steam Home and SteamVR running.
2. Connect the Frame directly to your Windows PC with a USB data cable. A charging-only cable cannot transfer files. Keep the Frame awake and allow this computer's device authorization on the headset if prompted.
3. In **Connect Frame**, choose **USB-C cable**. Setup first uses ADB already available on your computer's `PATH`, then falls back to its included ADB 37.0.1 files. **Advanced connection settings > Browse adb.exe** can select a specific installation. If you need replacement tools, use [Google's official Windows Platform Tools download and terms](https://developer.android.com/tools/releases/platform-tools), extract the complete package, and choose its `platform-tools\adb.exe`, keeping the companion DLLs next to it. Setup does not download SDK tools during an installation.
4. Enter the same Frame user password used for SSH and click **Test connection**. Setup selects the sole physical USB device automatically. If several physical USB devices are connected, unplug the others or enter the Frame's exact ADB serial in **Advanced connection settings**. If a serial cannot be verified as a physical USB connection, unplug other devices and leave the serial field blank for automatic detection. Emulators and network-connected ADB devices are not USB targets. Review the Frame's SSH host fingerprint when asked.
5. Continue with install, repair, library registration, or uninstall. Leave the cable attached until setup reports that it has disconnected. Setup removes only the temporary ADB forward it created and leaves the shared ADB server and other forwards running.

The cable carries encrypted SSH/SFTP traffic between the PC and Frame. **The Frame still needs its own internet connection** to fetch native source, the build container, and compiler dependencies. USB does not provide internet sharing or change Wi-Fi/Steam settings. Cable transfer may help on a weak or congested wireless network; actual speed depends on the cable, USB ports, and device. It does not speed up the native compilation phase. USB behavior has automated software coverage; physical Steam Frame USB transfer verification is pending. [Valve's USB/ADB guide](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging) and [Google's ADB reference](https://developer.android.com/tools/adb) describe the underlying connection and forwarding tools.

The installation bar fills from left to right and does not move backward during a run. Its overall percentage combines weighted stages with measured upload bytes and completed Ninja build tasks. During work without a measurable total, such as package setup or configuration, the bar holds its last value while the activity feed continues showing available output. This percentage describes completed work, not elapsed time or a finish-time estimate. Failure or cancellation preserves the reached progress; a remaining manual Steam or artwork step stays at 99%, and only full success reaches 100%.

Setup explicitly closes its SFTP and command channels and the underlying SSH connection before reporting completion. The activity feed shows disconnecting and disconnected stages; failure and cancellation also close that connection. USB cleanup removes only this operation's temporary ADB forward. Setup does not stop the shared ADB server or change the Frame's Wi-Fi or Steam streaming settings.

The included ADB executable, two companion DLLs, and unmodified notices are checksum-verified before being copied to `%LOCALAPPDATA%/HaloFrameInstaller/usb-tools/37.0.1`. This versioned cache remains after setup closes so a shared ADB server can keep using it without locking the EXE's temporary extraction folder. The selected client's protocol is checked against an already-running local ADB server; a mismatch stops USB setup without restarting that server. Setup also verifies that the temporary forwarded port listens only on this PC's loopback addresses before sending the SSH password. [Bundled-tool provenance and licenses](THIRD_PARTY.md#adb-for-usb-transfer).

These changes apply after you launch the new EXE and start a run. An installation already running in an older EXE keeps its existing behavior; downloading a replacement cannot change that ongoing process.

After you select valid local Xbox game data, the installer automatically loops the original Halo menu music. Validation and music preparation run in the background. Setup reads the menu loop from your own `ui.map`, decodes it at 12% of the original sample amplitude, and keeps the temporary audio on your Windows computer until the installer closes. No soundtrack is bundled, downloaded, or uploaded to the Frame. Repair using only maps already on the Frame has no local music preview. If music is unavailable, installation can continue.

### Supported Xbox ISO revisions

Use **Halo: Combat Evolved for the original Xbox**. **USA Rev 2 is validated with this installer.** Other retail revisions, including an original USA release or an image labeled **USA Rev 1**, and PAL releases are accepted when their actual map headers match one of these supported builds:

| Map-header build | Upstream region |
| --- | --- |
| `01.10.12.2276` | NTSC |
| `01.08.15.1749` | NTSC |
| `01.01.14.2342` | PAL |

These builds come from the [pinned port's compatibility table](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/source/cache/cache_files.c#L616-L631). Its [PAL conversion notes](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/linux/game/pal_tags.c#L4-L22) describe the shared NTSC maps across three retail releases. Setup checks the image contents, not its filename or a Rev label: it requires all 24 original Xbox version-5 maps from one supported build. Incomplete or mixed-build sets and unlisted builds are rejected. Halo PC/Custom Edition, Xbox 360 Anniversary, MCC, and Quest packages are unsupported inputs. Supply your own authorized retail ISO/XISO or extracted maps.

### Already have Halo installed?

Choose **Repair** in the **Game data** step, connect your Frame, and click **Repair Halo VR** in the last step. Setup detects the standard native folder `~/Games/HaloCENativeVR` and reinstalls the native executable, SDL library, controls/tutorial patch, and notices; it restores the required VR/control settings while preserving saves and unrelated settings. Valid original Xbox maps already on the Frame can be reused without selecting another ISO. If maps are missing or damaged, select a valid local image/maps folder and retry. Previous installs made by this installer or the original guided native setup are recognized. A hand-installed native game in the same folder can be adopted only through the explicit Repair action, after its native executable and original Xbox maps validate. Unknown folders and other install locations are not overwritten.

The old PC installation at `~/Games/HaloCEVR` is detected and explained separately. Its PC maps cannot be used for this native Xbox build. Setup installs the native version separately and does not automatically remove the PC version. Close the native game before repair. Program-file backups are retained in the owned build workspace, and a failed repair rolls back the affected files. **Add to Steam again** repairs library registration and adds missing library artwork; it does not rebuild the game.

With Steam running, setup uses the current client's library interface and verifies the native executable, launch options, VR flag, and disabled compatibility tool before reporting registration success. This interface is undocumented and may change with Steam updates. If it is unavailable, ambiguous, or cannot verify the result within its time limit, setup keeps the headset session running and shows manual steps. Use Steam's **Add a Game > Add a Non-Steam Game** to select `~/Games/HaloCENativeVR/halo`, apply the launch option below, and enable **Include in VR Library**. Leave forced compatibility tools disabled for this native Linux executable. **Add to Steam again** retries available library setup without rebuilding. If Steam is already closed, setup can use backed-up atomic library-file updates; it never shuts down, launches, or restarts the headset's Steam session.

### Automatic Steam library information

Install and Repair automatically update the native Steam shortcut, missing artwork, and **Halo CE VR — About & controls** note after the game is ready. There is no separate Steam info option to select. Save and close games, leave Steam Home running, and keep the headset connected until setup disconnects. If registration, artwork, or Notes remains pending at the end, **Add to Steam again** retries that step without transferring maps or rebuilding the game.

Open **Notes** on the Halo game's Steam details page or in its overlay to read the description and control guide. These are private game notes using Steam's normal notes synchronization. They do not replace the non-Steam About panel or add a store page, achievements, reviews, or another game's Steam identity. Existing notes and edited installer notes remain unchanged. If Notes is unavailable or synchronization cannot be verified, setup shows copyable text for manual use. Missing artwork or an icon awaiting Steam's shortcut-file persistence is reported separately and can be retried with **Add to Steam again**. Notes requires a running, verified Steam client; setup leaves a closed Steam client closed.

### Uninstall Halo VR

Choose **Uninstall** on the first page to remove the recognized, owned native installation at `~/Games/HaloCENativeVR` and its native Steam shortcut. You do not need an ISO or local maps for uninstall, but you must connect over SSH with the Frame's user password. Save and close games; keep Steam Home and SteamVR running. Setup asks the running client to remove the exact native shortcut from its active account, then verifies that removal before deleting game files. If the client interface is unavailable or removal cannot be verified, setup keeps the native game files and stops at 99%, explaining Steam's **Remove Non-Steam Game** option. An owned installation build still running also stops removal before deletion. Setup never shuts down or relaunches Steam. If Steam is already closed, automatic removal can use its backed-up library-file path across the local accounts.

**Keep my campaign saves in a backup (recommended)** is checked by default. Setup backs up saves inside the native game folder and the original config to `~/Games/HaloCENativeVR-saves-<operation ID>`, and reports the exact backup location. The recognized native folder, including its maps, program files, and config, is then removed; configured saves outside that folder remain untouched. Turning off the checkbox allows saves inside the removed folder to be deleted. Uninstall leaves unrelated games, foreign or unrecognized folders, and unrelated settings alone. The build cache remains available for troubleshooting. Setup disconnects its SSH session after the operation and reaches 100% only after completion.

With the client running, Steam controls artwork cleanup for the removed entry; setup does not delete its live grid files. With Steam already closed, setup removes only artwork matching the installer's known image hashes and preserves custom images.

## Xbox-style controls

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
| Both grips held | Recenter |

Motion aiming stays enabled. Smooth turning defaults to 90 degrees/second, refresh rate to 72 Hz, and render scale to 1.0. Repairs refresh the VR/control defaults and keep unrelated settings and saves. Head movement also satisfies the first-level look tutorial. The patch does not skip the campaign or increase combat difficulty.

The native shortcut uses this **per-game** launch option to prevent the same physical controller from being read through both OpenXR and Steam's virtual gamepad:

```text
SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=0 %command%
```

See [controls and patch details](CONTROLS.md).

## What gets installed

Game: `~/Games/HaloCENativeVR`, including `halo`, bundled SDL3, your maps, config, notices, and an ownership/provenance manifest. New-install saves are in that game's separate `save` folder; repairs preserve existing save locations. Build workspace: `~/.cache/halo-frame-installer`. Source is fetched at the fixed commit below, not a moving branch. Build cache is retained for troubleshooting. Setup does not remove another Halo installation or touch unrelated games.

The original Halo CE cover is shown inside the installer. The native shortcut receives missing portrait and landscape covers, a 1,920 × 620 original CE promotional banner, transparent title logo, and the project-drawn Master Chief helmet icon. With Steam running, setup uses its verified client interface, checks the active account and native executable, and verifies the artwork hashes. The icon is kept in the owned game's `.installer-artwork` folder so it survives the setup EXE closing. Its existing path is verified through read-only shortcut-file checks before changing it through Steam's API. Both running-client and already-closed file paths preserve custom art and icons, including different supported image extensions. An icon that cannot be verified is reported as pending rather than replacing an uncertain user choice.

The description and Xbox controls use **Steam Game Notes**. Setup appends one bounded note without replacing other notes or an edited installer note. Artwork and Notes have independent pending states; Install, Repair, and any completion retry use the same handling. No artwork download is needed. The new bundled images total less than 1 MB, with sources and exact hashes in the [artwork resource notice](../resources/artwork/README.md). The user confirmed the older entry and covers on the Frame tested with 1.2.3; the newer banner, logo, icon, and Notes still need a physical Frame check.

The renderer uses the Xbox game's data and translated Xbox shaders. Native OpenXR VR and competitive multiplayer come from the port. The PC-only Chimera, PC Restored maps, and HaloCEVR DLLs do not belong in this native build. Multiplayer requires compatible native/OpenCE protocol builds; Halo PC/Custom Edition/MCC servers and PC save files are incompatible.

## Sources and credits

- [OpenCE Steam Frame VR PR #85](https://github.com/OpenCommunityEdition/OpenCE/pull/85), by startupfoundry.
- [Exact VR source commit `88142798513ebd99fc7c6224023e8b44c05d0106`](https://github.com/startupfoundry/halo-ce-universal/tree/88142798513ebd99fc7c6224023e8b44c05d0106), with a documented local controller/tutorial patch.
- [Upstream native Linux/VR build instructions](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/linux/README.md#vr).
- [Valve's official Frame setup](https://partner.steamgames.com/doc/steamhardware/steamframe/setup) and [SSH/debugging instructions](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging).
- [Google's ADB connection and forwarding reference](https://developer.android.com/tools/adb) and [official Platform Tools download and terms](https://developer.android.com/tools/releases/platform-tools).
- [Original Xbox dashboard visual references](SOURCES.md#dashboard-visual-references) and [Halo CE artwork attribution and Steam Notes references](SOURCES.md#steam-library-artwork).

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
- **Build/download fails:** the error dialog shows a short failure headline; open **Show activity** or **Save log** for the full redacted details. Keep the Frame's build log and retry. Version 1.2.1 fixes the container dependency-installation permission errors (`setgroups`, `seteuid`, or APT cache permissions) seen in 1.2.0. Retry can reuse previously uploaded maps only when the complete map set matches the selected local data manifest and passes header and SHA256 verification; otherwise setup uploads fresh data. Reused data stays in its previous owned upload run and is verified again at build and finalization. A failed staging build does not replace an existing game or save.
- **Unsupported ISO or maps:** choose original Xbox retail data matching a [supported map build](#supported-xbox-iso-revisions). USA Rev 2 is validated; a filename containing Rev 1 or Rev 2 does not establish compatibility by itself. Keep all required maps from one release together.
- **Flat window instead of VR:** wake the headset and start SteamVR before launching. The port falls back to a flat window if no usable OpenXR session is available.
- **Controls doubled:** check the native shortcut's launch option above. Steam Input may otherwise add a second virtual controller stream.
- **Library entry absent:** click **Add to Steam again** to retry registration through the running client. If its library interface remains unavailable, use Steam's **Add a Non-Steam Game** with the executable and launch option above. Enable **Include in VR Library** and leave forced compatibility tools disabled in its properties. Setup's direct library-file edits require Steam to be already closed.
- **Artwork or description absent:** Install and Repair add these automatically. If setup reports pending Steam information, click **Add to Steam again** after the run. The description is under **Notes**, not the non-Steam About panel. Pending artwork, icon, or Notes is reported separately from the shortcut; manual Notes includes copyable text. Existing custom artwork and notes are kept. Direct file edits require Steam to be already closed; Notes needs the running client's interface.
- **Steam Home remains on a loading logo after an older installer run:** 1.2.3 removes the automatic shutdown request that disrupted the SteamOS-managed session in a reported case. It does not repair a session already in a failed state. Restart the Frame using its normal power controls, and contact Steam Support if Steam Home does not return. [Steam session safeguard and diagnostic sources](SOURCES.md#steam-session-safeguard).
- **Menu music unavailable:** select valid local original Xbox data containing `ui.map`; music starts automatically after validation. A repair using only remote maps cannot preview music. Playback errors do not block setup; Windows volume controls the final sound level.

The release executable is unsigned. Verify its SHA256 against the checksum in the release description; this project does not ask you to disable antivirus or other security protections. Review logs for private information before posting an issue.

## Develop and rebuild the executable

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m halo_frame_installer
.\.venv\Scripts\python scripts/build_release.py
```

Corresponding installer source and applicable third-party source/notices are available in the **[version 1.3.4 source tag](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/tree/v1.3.4)** so you can modify and rebuild it, including its LGPL Paramiko dependency. GitHub's automatically generated Source code ZIP is optional for developers and is not needed to run setup. ADB binaries are not checked into Git; [bundle_usb_tools.py](../scripts/bundle_usb_tools.py) downloads the pinned official archive during the executable build and verifies its archive and selected-file checksums before packaging. [resources/usb/manifest.json](../resources/usb/manifest.json) records those hashes and provenance, and the original notices are retained. The build script packages installer code/resources and verified ADB components with their notices; no retail game executable, user ISO, maps, SSH password, or private key is included. GitHub Actions runs tests and builds the Windows setup executable. A local rebuild also writes a source bundle and checksum file to `dist/`; the public release attaches only the clearly named mod installer executable and prints its checksum in the release description.

The workflow also includes an ARM64 Linux check, [check-build-container.py](../scripts/check-build-container.py), that uses the same rootless Podman arguments as the Frame build. It checks APT package installation, `setgroups`, `seteuid`, `setegid`, `chown`, and that container output belongs to the ordinary host user. The Windows executable CI job depends on that check as well as the unit tests. This container check uses no game data and does not replace a full Steam Frame installation test.

Before reporting a hardware test, record the SteamOS/SteamVR version, source commit, install status, and whether menu, campaign, Xbox controls, tutorial, and compatible multiplayer worked. Do not attach game data or credentials.
