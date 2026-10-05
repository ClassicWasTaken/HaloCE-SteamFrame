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

## Regenerating notices

Run the following in the same Python environment used for packaging:

```powershell
python scripts/gather_notices.py --download-sources
```

The script copies actual installed license files, the Python runtime's license and available Tcl/Tk terms. With `--download-sources`, it retrieves the checksum-verified official Paramiko source archive and the exact-version OpenSSL and Tcl license texts from their primary repositories. All generated paths are relative to `resources/licenses`. Regenerate these resources for every new dependency/runtime build and include the directory with its source and executable release.

See [SOURCES.md](SOURCES.md) for the game, VR, Steam Frame and SSH primary references.
