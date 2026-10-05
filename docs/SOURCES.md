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

[Upstream game-data instructions](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/README.md#game-data) require an **original Xbox Halo: Combat Evolved** disc image (`.iso` or `.xiso`) or its extracted maps. Upstream supports the original Xbox revisions and regions, including conversion of PAL map timing for play with NTSC maps.

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

## Build and installer dependencies

- [LLVM's signed Ubuntu package repository](https://apt.llvm.org/) supplies LLVM 22 inside the build container for the upstream `arm64_32` guest compiler target.
- [Podman's rootless operation](https://docs.podman.io/en/latest/markdown/podman.1.html#rootless-mode) isolates compiler dependencies from the headset's system installation.
- [SDL](https://github.com/libsdl-org/SDL/tree/release-3.4.16) provides native windowing, audio and gamepad support. [Its Steam virtual-gamepad hint](https://github.com/libsdl-org/SDL/blob/release-3.4.16/include/SDL3/SDL_hints.h) supports suppressing duplicate virtual-pad input for this game's shortcut.
- [Khronos OpenXR](https://github.com/KhronosGroup/OpenXR-SDK) supplies the OpenXR API headers used by the upstream VR implementation. The Frame's installed runtime supplies the active headset session.
- [Paramiko](https://www.paramiko.org/) provides SSH/SFTP for the Windows installer, using [cryptography](https://cryptography.io/), [bcrypt](https://github.com/pyca/bcrypt) and [PyNaCl](https://github.com/pyca/pynacl).
- [CPython](https://www.python.org/) and [Tcl/Tk](https://www.tcl.tk/) provide the installer runtime and guided desktop interface. [PyInstaller](https://pyinstaller.org/) creates the Windows executable.

Actual package versions, original license notices and source references are recorded in [third-party notices](THIRD_PARTY.md) and the [generated license manifest](../resources/licenses/manifest.json). The installer code's license does not replace the upstream or dependency licenses.

This product includes software developed by in <in@fishtank.com> (the upstream `extract-xiso` component).

## General preservation resources

User-suggested background links: [Vimm's Lair](https://vimm.net/) and [Internet Archive's about page](https://archive.org/about/). These are general references, not Halo file-download links, software dependencies, or assurances of game-data permissions. The installer selects a local original Xbox image/maps supplied by the user; it does not fetch commercial game files. The PC edition is not an input to the native Frame build.
