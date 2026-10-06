# Sources and acknowledgements

The installer builds the experimental native ARM64 Linux VR port of **Halo: Combat Evolved** from the revision below. It provides a guided installation; the decompilation, renderer, OpenXR implementation and networking are the work of the credited upstream contributors.

Sources were checked on 2026-10-05. Links to pinned files describe the build used here; moving documentation may describe newer behavior.

## Native game and VR

| Source | Contribution or verified requirement |
| --- | --- |
| [startupfoundry's native Steam Frame VR work, OpenCE PR #85](https://github.com/OpenCommunityEdition/OpenCE/pull/85) | OpenXR stereo, tracked head and controllers, native ARM64 host, desktop OpenGL and stereo multiview. This is experimental work in an open pull request. The normal upstream CI builds do not enable `--vr`. |
| [Pinned fork revision `88142798513ebd99fc7c6224023e8b44c05d0106`](https://github.com/startupfoundry/halo-ce-universal/tree/88142798513ebd99fc7c6224023e8b44c05d0106) | Exact source revision selected for this installer, rather than a moving branch. |
| [Upstream build instructions](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/linux/README.md#64-bit-arm) | Native ARM64 compiler requirements, SDL 3.4.16, musl 1.2.5, and the `linux_arm64` target. |
| [Upstream VR documentation](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/linux/README.md#vr) | `configure.py --vr`, OpenXR runtime requirements, motion aiming, gamepad mode, comfort options, and experimental limitations. |
| [OpenCommunityEdition/OpenCE](https://github.com/OpenCommunityEdition/OpenCE) | Community port and integration work from which the VR fork descends. |
| [bnunu/halo-1](https://github.com/bnunu/halo-1) and [punpckhdq/halo](https://github.com/punpckhdq/halo) | Decompilation lineage identified by the upstream README. |
| [Upstream XDK declarations](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/include/xdk/README.md) | The port supplies its own declarations; installing the proprietary Xbox SDK is unnecessary. |

The installer applies [its documented controller and tutorial patch](../resources/frame-controls.patch) to that pinned revision. [Controls and defaults](CONTROLS.md) distinguish these changes from upstream behavior. Performance depends on game scene, headset software and settings; native ARM64 does not imply unlimited performance.

## Game data and compatibility

[Upstream game-data instructions](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/README.md#game-data) require an **original Xbox Halo: Combat Evolved** disc image (`.iso` or `.xiso`) or its extracted maps. This installer uses the exact released-map build list in the [pinned cache compatibility table](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/source/cache/cache_files.c#L616-L631):

| Accepted Xbox version-5 map build | Upstream region |
| --- | --- |
| `01.10.12.2276` | NTSC |
| `01.08.15.1749` | NTSC |
| `01.01.14.2342` | PAL |

**USA Rev 2 is validated with this installer.** Other original Xbox retail revisions and regions, including an image labeled USA Rev 1 or the original USA release, are accepted only when all 24 required maps have one of these builds. [Upstream PAL conversion notes](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/linux/game/pal_tags.c#L4-L22) identify shared NTSC maps across three releases and explain the PAL timing conversion. Those source files do not provide a definitive filename-to-Rev-label mapping; setup validates actual headers instead of trusting a filename. Incomplete or mixed-build sets and other build strings are rejected. This is a supported-data rule, not a claim that every disc pressing has been tested on a Frame.

Select a local disc image or maps that you are authorized to use. The installer checks original Xbox map headers and extracts the required data locally. The repository and downloadable installer contain no game disc image or commercial map data and provide no unauthorized game-download links.

Halo PC, Custom Edition, Xbox 360 Anniversary and MCC data are different formats. This is the native **Steam Frame** Linux VR port; the Android port in the upstream repository is not a promise of a Quest VR installation. PC Chimera, PC Restored map replacements and HaloCEVR DLLs are not loaded by this ARM64 build. Its native renderer and VR implementation supply the relevant graphics and headset support. PC Halo saves and profiles also differ from the native port's Xbox formats.

[Upstream multiplayer](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/README.md#multiplayer) supports LAN and internet play among compatible builds of this port. The [netcode design](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/linux/NETCODE.md) describes its replacement networking. Use matching native/OpenCE protocol versions; compatibility with legacy Halo PC, Custom Edition, MCC or retail Xbox servers is not established by this project.

## Steam Frame setup and connection

| Primary reference | Installer guidance |
| --- | --- |
| [Valve: Setting up your Steam Frame for development](https://partner.steamgames.com/doc/steamhardware/steamframe/setup) | In the headset, open **Steam Settings > System > Enable Developer Mode**. Open **Developer > Set User Password** and choose a password. The hostname is under **Steam Settings > System > Hostname**. |
| [Valve: Steam Frame Debugging](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging) | Developer Mode enables SSH. Valve's default login is `ssh steamos@frame`, using the password you set. |
| [OpenSSH manuals](https://www.openssh.org/manual.html) and [Paramiko host-key policies](https://docs.paramiko.org/en/stable/api/client.html#paramiko.client.MissingHostKeyPolicy) | SSH host keys identify the destination device. Review the first-connection fingerprint; an unexpected changed key should stop the connection. |

SteamOS has a read-only system filesystem. This installer uses a user-owned game folder and an unprivileged build container; its process does not require disabling that protection or changing system packages.

### Steam session safeguard

[Valve's Frame debugging documentation](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging) documents the standalone SteamOS environment, developer SSH access, remote headset view, and Steam log location. It does not provide a current Frame-specific command to stop and recreate the headset's Steam session from SSH.

During investigation of a reported loading-logo failure after a 1.2.2 run, the tested Frame's installed SteamOS user service was configured to restart Steam automatically. Device diagnostics showed that service in a failed start-limit state after repeated supervised restarts while the VR service remained active. The installer had timed out waiting for its requested Steam shutdown, leaving the library files unchanged; its separate client-launch path was not reached. These are observations from the installed service and that device, not a claim that every Frame loading-logo problem has the same cause. No private logs or credentials are included here.

Version 1.2.3 removes automatic Steam shutdown and separate client launches. It keeps Steam Home and SteamVR running, guards against directly editing a running client's library/artwork files, and reports manual steps when required. The saved-and-closed-games checkbox permits game-file work; it is not permission to restart Steam. Automatic file registration and removal operate only when Steam is already closed. This safeguard prevents the installer from issuing the problematic shutdown request; recovering a previously failed headset session is a separate action.

The [live library helper](../resources/steam_live.py) uses the currently installed client's `SteamClient.Apps` interface through its existing local CEF context. These are observed, undocumented client interfaces rather than a stable public Steamworks API. The helper checks endpoint ownership, capabilities, exact native executable identity, and readback within bounded requests. Artwork uses the client's `SetCustomArtworkForApp` method, with the active account matched to one owned local profile, existing custom images preserved, and the resulting files verified against the bundled source hashes. It does not enable a new remote debugger, change the session launch command, or write the live shortcut VDF or grid files directly. Unsupported or unverified results produce manual Add/Remove/artwork steps. Live removal affects the active client account and leaves artwork files under Steam's control; already-closed removal can handle local account files and removes only known installer artwork hashes. Future Steam builds may need an updated adapter.

The final 1.2.3 helper was tested on one Frame for native shortcut removal and re-addition, exact executable/launch/VR/compatibility settings, and fresh creation of cover and landscape artwork with exact source-hash readback. A prior check preserved and verified both existing managed image hashes. Steam and VR services remained active and unchanged, and the game binary was unchanged. The user confirmed Steam Home worked after separate recovery through the device's installed managed launcher. These checks do not establish a complete fresh installation, game uninstall, visual artwork check, or listening test.

## Build and installer dependencies

- [LLVM's signed Ubuntu package repository](https://apt.llvm.org/) supplies LLVM 22 inside the build container for the upstream `arm64_32` guest compiler target.
- [Ninja's environment-variable documentation](https://ninja-build.org/manual.html#_environment_variables) defines the finished and total build-task counts used for measured compilation progress. The installer's overall percentage combines phase weights, transferred bytes, and completed build tasks; it is not a time or performance estimate.
- [Podman's rootless operation](https://docs.podman.io/en/latest/markdown/podman.1.html#rootless-mode) isolates compiler dependencies from the headset's system installation.
- [Podman run: container user and user namespaces](https://docs.podman.io/en/latest/markdown/podman-run.1.html#user-u-user-group) documents how `--user` selects the container UID/GID and how `--userns=keep-id` otherwise starts the process as the caller's UID. Setup explicitly uses `--user=0:0` for container dependency installation while Podman remains rootless under the ordinary host user. [Its security options](https://docs.podman.io/en/latest/markdown/podman-run.1.html#security-opt-option) define the retained `no-new-privileges` restriction.
- [SDL](https://github.com/libsdl-org/SDL/tree/release-3.4.16) provides native windowing, audio and gamepad support. [Its Steam virtual-gamepad hint](https://github.com/libsdl-org/SDL/blob/release-3.4.16/include/SDL3/SDL_hints.h) supports suppressing duplicate virtual-pad input for this game's shortcut.
- [Khronos OpenXR](https://github.com/KhronosGroup/OpenXR-SDK) supplies the OpenXR API headers used by the upstream VR implementation. The Frame's installed runtime supplies the active headset session.
- [Paramiko](https://www.paramiko.org/) provides SSH/SFTP for the Windows installer, using [cryptography](https://cryptography.io/), [bcrypt](https://github.com/pyca/bcrypt) and [PyNaCl](https://github.com/pyca/pynacl).
- [CPython](https://www.python.org/) and [Tcl/Tk](https://www.tcl.tk/) provide the installer runtime and guided desktop interface. [PyInstaller](https://pyinstaller.org/) creates the Windows executable.

Actual package versions, original license notices and source references are recorded in [third-party notices](THIRD_PARTY.md) and the [generated license manifest](../resources/licenses/manifest.json). The installer code's license does not replace the upstream or dependency licenses.

This product includes software developed by in <in@fishtank.com> (the upstream `extract-xiso` component).

## Dashboard visual references

- [Martin Nobel's original Xbox dashboard screenshots](https://www.martinnobel.com/techresearch/original-xbox-dashboard-screenshots) document the console's main menu, settings, and other screens. They serve as visual references for the installer's dark panels, green accents, and beveled interface.
- [Microsoft's November 5, 2001 Xbox launch campaign announcement](https://news.microsoft.com/source/2001/11/05/microsoft-broadcast-ad-campaign-electrifies-gamers-for-the-launch-of-xbox-on-nov-15/) describes the original console's glowing green jewel campaign and identifies Halo among its launch titles.

These links credit visual and historical references. Dashboard styling is an independent installer interface; the project is unaffiliated with Microsoft or Xbox. Original screenshots, game artwork, and trademarks retain their respective owners' rights.

## Steam library artwork

The bundled portrait image is the original **Halo: Combat Evolved** cover from [Halopedia's cover-art file page](https://www.halopedia.org/File:HCE_Cover_Art.jpg), with the [original JPEG](https://www.halopedia.org/images/8/8e/HCE_Cover_Art.jpg). Halopedia records the [official Halo Facebook image](https://www.facebook.com/Halo/photos/a.137195553028391/1561119617302637/) as its source. The landscape library image arranges the same cover in a wider layout without stretching it.

The cover remains copyrighted Microsoft/Halo artwork; the installer's MIT license does not apply to it. Source attribution and exact hashes are retained in the [artwork resource notice](../resources/artwork/README.md) and described in [THIRD_PARTY.md](THIRD_PARTY.md#dashboard-and-library-artwork). A thumbnail appears inside the installer. The library images are applied only to its native Halo shortcut, preserving user-selected custom art. Artwork registration has not yet been visually checked on a Frame.

## Local Halo menu music

The preview reads only the `sound\music\title1\loops` sound tag from the user's selected original Xbox `ui.map`, either inside an ISO/XISO or in extracted maps. Cache and sound structures are based on the pinned native port's [cache_files.c](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/source/cache/cache_files.c) and [sound_definitions.h](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/source/sound/sound_definitions.h). Xbox ADPCM decoding follows its [dsound_sdl.c implementation](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/linux/src/dsound_sdl.c).

The installer decodes the loop into a private temporary Windows WAV with a fixed 12% sample-amplitude gain. Playback loops automatically after local game data validates. Closing the installer stops playback and clears its temporary audio. No soundtrack is present in the repository or executable, fetched from a website, or uploaded over SSH. Audio-file extensions are rejected by the release packager. Remote-only repair has no local audio preview, and an unavailable preview does not block installation. The original music remains copyrighted game content; the installer's code license does not apply to it. Playback still needs a listening check.

## General preservation resources

User-suggested background links: [Vimm's Lair](https://vimm.net/) and [Internet Archive's about page](https://archive.org/about/). These are general references, not Halo file-download links, software dependencies, or assurances of game-data permissions. The installer selects a local original Xbox image/maps supplied by the user; it does not fetch commercial game files. The PC edition is not an input to the native Frame build.
