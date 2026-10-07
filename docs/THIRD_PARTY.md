# VR mod and third-party notices

This community VR mod installer's original code has its own [MIT license](../LICENSE). Each dependency keeps its own license. Original notice text is included under [resources/licenses](../resources/licenses); [manifest.json](../resources/licenses/manifest.json) records package versions, notice hashes and source URLs from the environment used to build the Windows executable.

The repository and executable include no retail game executable, disc image, maps, product keys, or soundtrack, and the installer does not download these files. Users supply authorized original Xbox game data. Copyrighted Halo artwork and trademarks remain separate from the installer code's license, as detailed below. Upstream source licenses are reported as published by their maintainers; this project does not independently certify the source's legal status. This is an unaffiliated community project.

The manifest includes build and test dependencies as well as runtime dependencies, so an entry does not imply that every file of that package is embedded in the executable. It records no machine paths, passwords, private SSH keys or game data.

## Windows mod installer

| Component | Initial build version | License and use |
| --- | --- | --- |
| [CPython](https://www.python.org/) | 3.12.14 | PSF license and retained component notices. Python runtime for the guided installer. Original text: [Python-LICENSE.txt](../resources/licenses/runtime/Python-LICENSE.txt). |
| [Tcl/Tk](https://www.tcl.tk/) | Tcl/Tk 8.6 | Tcl/Tk permissive notices. Desktop interface through `tkinter`. Retained [Tcl terms](../resources/licenses/runtime/tcl-LICENSE.terms) and [installed Tk terms](../resources/licenses/runtime/tcl-tk/tk8.6/license.terms). |
| [Paramiko](https://github.com/paramiko/paramiko/tree/4.0.0) | 4.0.0 | LGPL-2.1. SSH and SFTP. Full [license](../resources/licenses/packages/paramiko/paramiko-4.0.0.dist-info/licenses/LICENSE) and [source archive](../resources/licenses/sources/paramiko-4.0.0.tar.gz) are included. |
| [cryptography](https://github.com/pyca/cryptography) | 50.0.2 | Apache-2.0 OR BSD-3-Clause. Cryptographic primitives used by SSH. Both notices are retained in the package's license folder. |
| [bcrypt](https://github.com/pyca/bcrypt) | 5.0.0 | Apache-2.0. Password/key derivation support. |
| [PyNaCl](https://github.com/pyca/pynacl) | 1.6.2 | Apache-2.0, with retained ISC notice for bundled libsodium. SSH cryptographic support. |
| [CFFI](https://github.com/python-cffi/cffi) | 2.1.1 | MIT-0. Foreign-function support for native dependencies. |
| [pycparser](https://github.com/eliben/pycparser) | 3.0 | BSD-3-Clause. CFFI parsing dependency. |
| [Invoke](https://github.com/pyinvoke/invoke) | 3.0.3 | BSD-2-Clause. Paramiko dependency. |
| [OpenSSL](https://github.com/openssl/openssl) | 3.5.8 / 4.0.3 | Apache-2.0. The Python `ssl` runtime and cryptography wheel use different builds. Exact-version [3.5.8](../resources/licenses/runtime/openssl-3.5.8-LICENSE.txt) and [4.0.3](../resources/licenses/runtime/openssl-4.0.3-LICENSE.txt) license texts are retained. |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | 6.22.3 | GPL-2.0-or-later with its bootloader exception; certain runtime modules/hooks use Apache-2.0. Used to freeze the installer. The complete [COPYING text](../resources/licenses/packages/pyinstaller/pyinstaller-6.22.3.dist-info/licenses/COPYING.txt) preserves these distinctions. |
| [PyInstaller community hooks](https://github.com/pyinstaller/pyinstaller-hooks-contrib) | 2026.8 | GPL-2.0-or-later for ordinary build hooks, Apache-2.0 for bundled runtime hooks. Complete notice retained. |

The generated inventory also retains notices for altgraph, colorama, packaging, pefile, pywin32-ctypes, setuptools and its vendored components, pip, pytest, iniconfig, pluggy and Pygments when installed in the build environment. These packages keep the terms recorded in their original notice files. Future builds should use their own generated manifest rather than treating this initial version table as a dependency lock file.

### ADB for USB transfer

The Windows installer includes **ADB 37.0.1 (protocol 1.0.41)**: `adb.exe`, `AdbWinApi.dll`, and `AdbWinUsbApi.dll`, from the pinned [official Google Windows archive](https://dl.google.com/android/repository/platform-tools_r37.0.1-win.zip). The archive SHA256 is `45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99`. [The USB manifest](../resources/usb/manifest.json) records that provenance and each selected file's checksum; the package's [unmodified NOTICE.txt](../resources/usb/NOTICE.txt) is retained. ADB is separate from the installer's original MIT code; its component licenses remain in force. The installer does not redistribute the complete Android SDK or download SDK tools during setup.

Google's [Platform Tools download terms](https://developer.android.com/tools/releases/platform-tools), section 3.5, state that open-source SDK components are governed by their respective open-source licenses. AOSP provides the [ADB notice](https://android.googlesource.com/platform/packages/modules/adb/+/1cf2f017d312f73b3dc53bda85ef2610e35a80e9/NOTICE), [Windows AdbWinApi source notice](https://android.googlesource.com/platform/development/+/88f7870b2c652922dc2afb01c076737e8bc50130/host/windows/usb/api/AdbWinApi.cpp), and [Windows AdbWinUsbApi source notice](https://android.googlesource.com/platform/development/+/88f7870b2c652922dc2afb01c076737e8bc50130/host/windows/usb/winusb/AdbWinUsbApi.cpp). Their notices and the package's third-party notices are preserved rather than replaced by this project's license.

[Google's ADB reference](https://developer.android.com/tools/adb) describes the USB connection and port-forwarding feature used here. Setup forwards encrypted SSH/SFTP to the Frame rather than using ADB to copy game data directly. An advanced option can select an existing `adb.exe`; replacements and their accompanying DLLs can be obtained from Google's official download page under its displayed terms.

ADB binaries are ignored by Git and regenerated by [bundle_usb_tools.py](../scripts/bundle_usb_tools.py) during executable builds. The source tag includes the helper, pinned manifest, and notices needed to reproduce that packaging. At runtime, checksum-verified bundled files and notices are copied to `%LOCALAPPDATA%/HaloFrameInstaller/usb-tools/37.0.1`; this persistent cache lets a shared ADB server outlive setup without holding the one-file EXE's temporary extraction open.

### Paramiko source and modification

Paramiko remains unmodified by this installer. Its complete official 4.0.0 source distribution is supplied alongside its LGPL notice. The included source archive is verified against the SHA-256 published in [PyPI's version metadata](https://pypi.org/pypi/paramiko/4.0.0/json); its digest and source URL are recorded in the manifest.

You may modify Paramiko and rebuild the installer with that modified library. This project imposes no restriction on reverse engineering for debugging such library modifications. Obtain the installer source for the matching release and follow the [source build instructions](SETUP.md#develop-and-rebuild-the-executable). After installing the build dependencies, replace Paramiko in that environment with your modified source before the executable-freezing step, for example:

```powershell
python -m pip install --no-deps --force-reinstall C:\path\to\modified-paramiko
```

Then rebuild using the provided packaging script. The installer source, resources and build scripts are available in this repository; the ordinary GitHub source download contains them. The separate library retains its LGPL terms.

## Native game built on the Frame

The Windows download contains the mod installer and build instructions; no retail game executable, disc image, maps, product keys, or soundtrack is included. The native program is built from pinned upstream source on the Frame. Its upstream license and component notices remain applicable to that build, separately from rights in retail game content.

| Upstream component | Notice/reference |
| --- | --- |
| [Halo native port / decompilation](https://github.com/startupfoundry/halo-ce-universal/blob/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/LICENSE.md) | CC0-1.0 for the upstream source. This does not grant rights in the commercial game data or third parties' rights. |
| [Local VR integration patch](../resources/frame-controls.patch) | Documented controller, tutorial, vehicle, menu, tracking and renderer changes to the pinned upstream source; see [CONTROLS.md](CONTROLS.md). |
| [astromaddie/HaloCE-VR, reviewed revision](https://github.com/astromaddie/HaloCE-VR/tree/cff675537d961051d4aaf016c1e437542420b7df) | Menu, radar and optional buffer-streaming adaptation reference. Its [published source license](https://github.com/astromaddie/HaloCE-VR/blob/cff675537d961051d4aaf016c1e437542420b7df/LICENSE.md) is CC0-1.0; component notices and rights in retail game data remain separate. |
| [SDL 3.4.16](https://github.com/libsdl-org/SDL/blob/release-3.4.16/LICENSE.txt) | zlib license; retain the original notice with the native library. |
| [musl 1.2.5](https://git.musl-libc.org/cgit/musl/tree/COPYRIGHT?h=v1.2.5) | MIT and notices identified in its COPYRIGHT file. Used for the upstream ILP32 guest. |
| [Khronos OpenXR SDK headers](https://github.com/startupfoundry/halo-ce-universal/blob/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/port/third_party/openxr/README.md) | OpenXR SDK 1.1.63, Apache-2.0 OR MIT. Header provenance is documented upstream. |
| [mbedTLS, expat, miniupnpc, KCP, tomlc17 and stb](https://github.com/startupfoundry/halo-ce-universal/tree/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/port/third_party) | Their individual upstream license files apply. Preserve the actual files when producing the native installation. |
| [extract-xiso](https://github.com/startupfoundry/halo-ce-universal/blob/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/port/third_party/extract-xiso/LICENSE.TXT) | Custom BSD-style notice with acknowledgement and attribution conditions. This product includes software developed by in <in@fishtank.com>. |
| [Upstream font resources](https://github.com/startupfoundry/halo-ce-universal/tree/2ae0ee4e3e8a4dfdadfd528a5b085ca699fc9ea4/port/assets/fonts) | Retain Overpass's SIL Open Font License and Newtown's public-domain notice when using those upstream resources. |

The rootless build environment installs [Ubuntu packages](https://ubuntu.com/legal/open-source) and [LLVM](https://llvm.org/docs/DeveloperPolicy.html#license) under their own licenses inside its container. The installer does not relicense those tools or SteamOS/SteamVR. Game artwork, names and data remain the property of their respective rights holders.

## Dashboard and library artwork

The dashboard's circular core, panels, and green menus are independently drawn project resources covered by the project's MIT license. The original Xbox dashboard screenshots and Microsoft's launch-campaign announcement are credited as visual/historical references in [SOURCES.md](SOURCES.md#dashboard-visual-references); the interface is not an official Xbox or Microsoft application.

The Windows installer icon in 1.3.2 is the classic Halo PC helmet-and-shoulders application icon. The [unchanged HaloNet ICO](https://halonet.net/favicon.ico) was verified against icon group 102 of the locally installed retail `halo.exe`; only the icon was copied. Its original 12 image entries are embedded in the installer, and its 48-pixel RGBA frame supplies the Tk icon. The [icon resource notice](../resources/ui/README.md) records exact hashes and provenance. This copyrighted Halo artwork is separate from the project's MIT license.

The earlier original project drawing of Master Chief's helmet remains the Steam shortcut icon. Its SVG source and PNG rendition are in `resources/artwork`. The project's MIT license covers its drawing code. Microsoft retains the underlying rights in Halo, Master Chief, the character design, and associated trademarks; those rights are separate from the installer code's license.

The bundled Halo CE portrait cover and the landscape library layout retain copyrighted Microsoft/Halo cover artwork. The [Halopedia file page](https://www.halopedia.org/File:HCE_Cover_Art.jpg) identifies it as Halo: Combat Evolved cover art and records an [official Halo Facebook image](https://www.facebook.com/Halo/photos/a.137195553028391/1561119617302637/) as the source. This artwork is separate from the installer code's MIT license and is not represented as public domain or freely licensed. Attribution does not transfer rights in the cover or the Halo/Xbox trademarks.

A cover thumbnail identifies Halo inside the installer, and the portrait and landscape images identify the native Halo shortcut in the user's Steam library. The wider image preserves the cover proportions. Version 1.3.1 also includes a cropped original CE promotional banner from [the Xbox press-image record](https://www.halopedia.org/File:HCE_MC_Scorpion.jpg) and a resized transparent [Halo CE title logo](https://www.halopedia.org/File:Halo_-_Combat_Evolved_Logo_Huge.png). These retain Microsoft's artwork and trademark rights and are separate from the code's MIT license. The persistent shortcut icon is a PNG copy of the project's existing helmet drawing, with the same underlying character/trademark distinction above.

Existing library art and icons are retained, including custom images with another supported file extension; missing assets can be installed. Exact image hashes, original-image hashes, and source attribution are in the [artwork resource notice](../resources/artwork/README.md). The optional artwork preparation utility uses Pillow only during development, not in the frozen installer runtime. The repository and executable still contain no disc image, commercial map data, product key, or commercial game binary.

The Steam Notes description is original summary and control-guide text, not copied store text. Notes remain a private Steam feature governed by Steam's own behavior; no Steam client code is redistributed by the helper. Observed client interfaces are credited in [SOURCES.md](SOURCES.md#description-and-controls-in-steam-notes).

## README gameplay image

`docs/images/halocevr-steam-frame-example.jpeg` is an unchanged community screenshot by [u/Sea-Communication760](https://www.reddit.com/r/virtualreality/comments/1wpvi8n/halo_halocevr_working_great_on_steam_frame/), showing the PC HaloCEVR mod on Steam Frame through Proton ARM. It is labeled as a community example and is not a native 1.4.0 capture. The screenshot and underlying Halo content retain their respective rights; the installer's MIT code license does not apply to this image. See [the image source notice](images/README.md) for its original URL and SHA256.

## User-supplied menu audio

The original Halo menu music is not bundled with the installer. After the user selects valid local original Xbox data, setup reads the menu loop from that game's `ui.map`, decodes it quietly to a private temporary WAV, and automatically plays it locally. It is not downloaded or uploaded to the Frame, and its temporary decoded file is cleared on close. Repair with only remote maps does not supply a preview. The original music retains its rights holders' copyright and is separate from the installer's MIT code license.

The cache layout, sound definitions, and Xbox ADPCM algorithm are based on the pinned native port's CC0 source files credited in [SOURCES.md](SOURCES.md#local-halo-menu-music). The implementation is included as [music.py](../src/halo_frame_installer/music.py). The release packager rejects `.wav`, `.mp3`, `.ogg`, and `.wma` files to keep soundtrack data out of the executable and source bundle.

## Regenerating notices

Run the following in the same Python environment used for packaging:

```powershell
python scripts/gather_notices.py --download-sources
```

The script copies actual installed license files, the Python runtime's license and available Tcl/Tk terms. With `--download-sources`, it retrieves the checksum-verified official Paramiko source archive and the exact-version OpenSSL and Tcl license texts from their primary repositories. All generated paths are relative to `resources/licenses`. Regenerate these resources for every new dependency/runtime build and include the directory with its source and executable release.

See [SOURCES.md](SOURCES.md) for the game, VR, Steam Frame and SSH primary references.
