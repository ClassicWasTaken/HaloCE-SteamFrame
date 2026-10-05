# Third-party software notices

The installer code has its own [MIT license](../LICENSE). Each dependency keeps its own license. Original notice text is included under [resources/licenses](../resources/licenses); [manifest.json](../resources/licenses/manifest.json) records package versions, notice hashes and source URLs from the environment used to build the Windows executable.

The manifest includes build and test dependencies as well as runtime dependencies, so an entry does not imply that every file of that package is embedded in the executable. It records no machine paths, passwords, private SSH keys or game data.

## Windows installer

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

### Paramiko source and modification

Paramiko remains unmodified by this installer. Its complete official 4.0.0 source distribution is supplied alongside its LGPL notice. The included source archive is verified against the SHA-256 published in [PyPI's version metadata](https://pypi.org/pypi/paramiko/4.0.0/json); its digest and source URL are recorded in the manifest.

You may modify Paramiko and rebuild the installer with that modified library. This project imposes no restriction on reverse engineering for debugging such library modifications. Obtain the installer source for the matching release and follow the [source build instructions](../README.md). After installing the build dependencies, replace Paramiko in that environment with your modified source before the executable-freezing step, for example:

```powershell
python -m pip install --no-deps --force-reinstall C:\path\to\modified-paramiko
```

Then rebuild using the provided packaging script. The installer source, resources and build scripts are available in this repository; the ordinary GitHub source download contains them. The separate library retains its LGPL terms.

## Native game built on the Frame

The Windows download contains the installer and build instructions, not the commercial game's maps or disc image. The native program is built from pinned upstream source on the Frame. Its upstream license and component notices remain applicable to that build.

| Upstream component | Notice/reference |
| --- | --- |
| [Halo native port / decompilation](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/LICENSE.md) | CC0-1.0 for the upstream source. This does not grant rights in the commercial game data or third parties' rights. |
| [Local controller/tutorial patch](../resources/frame-controls.patch) | A documented modification of the pinned upstream source; see [CONTROLS.md](CONTROLS.md). |
| [SDL 3.4.16](https://github.com/libsdl-org/SDL/blob/release-3.4.16/LICENSE.txt) | zlib license; retain the original notice with the native library. |
| [musl 1.2.5](https://git.musl-libc.org/cgit/musl/tree/COPYRIGHT?h=v1.2.5) | MIT and notices identified in its COPYRIGHT file. Used for the upstream ILP32 guest. |
| [Khronos OpenXR SDK headers](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/third_party/openxr/README.md) | OpenXR SDK 1.1.63, Apache-2.0 OR MIT. Header provenance is documented upstream. |
| [mbedTLS, expat, miniupnpc, KCP, tomlc17 and stb](https://github.com/startupfoundry/halo-ce-universal/tree/88142798513ebd99fc7c6224023e8b44c05d0106/port/third_party) | Their individual upstream license files apply. Preserve the actual files when producing the native installation. |
| [extract-xiso](https://github.com/startupfoundry/halo-ce-universal/blob/88142798513ebd99fc7c6224023e8b44c05d0106/port/third_party/extract-xiso/LICENSE.TXT) | Custom BSD-style notice with acknowledgement and attribution conditions. This product includes software developed by in <in@fishtank.com>. |
| [Upstream font resources](https://github.com/startupfoundry/halo-ce-universal/tree/88142798513ebd99fc7c6224023e8b44c05d0106/port/assets/fonts) | Retain Overpass's SIL Open Font License and Newtown's public-domain notice when using those upstream resources. |

The rootless build environment installs [Ubuntu packages](https://ubuntu.com/legal/open-source) and [LLVM](https://llvm.org/docs/DeveloperPolicy.html#license) under their own licenses inside its container. The installer does not relicense those tools or SteamOS/SteamVR. Game artwork, names and data remain the property of their respective rights holders.

## Dashboard and library artwork

The dashboard's circular core, panels, and green menus are independently drawn project resources covered by the project's MIT license. The original Xbox dashboard screenshots and Microsoft's launch-campaign announcement are credited as visual/historical references in [SOURCES.md](SOURCES.md#dashboard-visual-references); the interface is not an official Xbox or Microsoft application.

The installer icon is an original project drawing of Master Chief's helmet, with olive armor and a gold visor, created in code and supplied as SVG, PNG, and multi-size ICO resources. The project's MIT license covers its drawing code. Microsoft retains the underlying rights in Halo, Master Chief, the character design, and associated trademarks; those rights are separate from the installer code's license.

The bundled Halo CE portrait cover and the landscape library layout retain copyrighted Microsoft/Halo cover artwork. The [Halopedia file page](https://www.halopedia.org/File:HCE_Cover_Art.jpg) identifies it as Halo: Combat Evolved cover art and records an [official Halo Facebook image](https://www.facebook.com/Halo/photos/a.137195553028391/1561119617302637/) as the source. This artwork is separate from the installer code's MIT license and is not represented as public domain or freely licensed. Attribution does not transfer rights in the cover or the Halo/Xbox trademarks.

A cover thumbnail identifies Halo inside the installer, and the portrait and landscape images identify the native Halo shortcut in the user's Steam library. The wider image preserves the cover proportions. Existing library art is retained, including custom images with another supported file extension; missing images can be installed. Exact image hashes and source attribution are in the [artwork resource notice](../resources/artwork/README.md). The repository and executable still contain no disc image, commercial map data, product key, or commercial game binary.

## User-supplied menu audio

The original Halo menu music is not bundled with the installer. After the user selects valid local original Xbox data, setup reads the menu loop from that game's `ui.map`, decodes it quietly to a private temporary WAV, and can play it locally with a mute control. It is not downloaded or uploaded to the Frame, and its temporary decoded file is cleared on close. Repair with only remote maps does not supply a preview. The original music retains its rights holders' copyright and is separate from the installer's MIT code license.

The cache layout, sound definitions, and Xbox ADPCM algorithm are based on the pinned native port's CC0 source files credited in [SOURCES.md](SOURCES.md#local-halo-menu-music). The implementation is included as [music.py](../src/halo_frame_installer/music.py). The release packager rejects `.wav`, `.mp3`, `.ogg`, and `.wma` files to keep soundtrack data out of the executable and source bundle.

## Regenerating notices

Run the following in the same Python environment used for packaging:

```powershell
python scripts/gather_notices.py --download-sources
```

The script copies actual installed license files, the Python runtime's license and available Tcl/Tk terms. With `--download-sources`, it retrieves the checksum-verified official Paramiko source archive and the exact-version OpenSSL and Tcl license texts from their primary repositories. All generated paths are relative to `resources/licenses`. Regenerate these resources for every new dependency/runtime build and include the directory with its source and executable release.

See [SOURCES.md](SOURCES.md) for the game, VR, Steam Frame and SSH primary references.
