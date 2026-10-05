# Halo Steam Frame Setup 1.2.1

Download only **[Halo-Steam-Frame-Setup-1.2.1.exe](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/releases/download/v1.2.1/Halo-Steam-Frame-Setup-1.2.1.exe)**. This is the complete Windows installer; no ZIP, Python installation, or extra installer file is needed.

Version 1.2.1 fixes dependency installation failing inside the native ARM64 build container with `setgroups`, `seteuid`, and APT permission errors. Setup now explicitly starts the build as root **inside the container** (`--user=0:0`), while Podman still runs rootless as the ordinary `steamos` host user and retains `no-new-privileges`. SteamOS system packages and its read-only root filesystem are unchanged.

- Retry can reuse maps uploaded during a failed attempt only after the complete set matches the selected local manifest and passes map-header and SHA256 verification. Setup records a reference to the previous owned upload run and verifies its data again at build and finalization. Missing, damaged, or different data is uploaded again.
- Error dialogs show a concise failure headline without internal `HFI_PROGRESS` protocol lines and direct users to **Show activity** or **Save log** for the full redacted details.
- Adds an ARM64 Linux CI check using the same rootless container arguments as the Frame build. It exercises APT package installation, UID/GID and group changes, `chown`, and output ownership on the host before the workflow builds the Windows EXE.
- Retains the original Xbox dashboard UI, in-app Halo CE cover, Steam portrait and landscape artwork, Master Chief executable icon, and local menu music at 12% sample amplitude with a mute toggle.
- Retains Xbox-style controls, the tutorial head-look fix, safe repairs that preserve saves and unrelated settings, and library-registration retry without rebuilding.

If 1.2.0 failed during the compiler dependency step, close that installer, run this version, select the same original Xbox ISO/maps, and retry. Setup verifies retained map data before reusing it. The failed build does not replace an existing game.

The **[version 1.2.1 source tag](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/tree/v1.2.1)** contains the corresponding installer source, build scripts, and applicable third-party notices/source, including the LGPL Paramiko dependency. GitHub's generated Source code ZIP is optional for developers. The public release attaches one clearly labeled installer EXE and includes its SHA256 in this release description.

The native ARM64/OpenXR game remains experimental upstream work. Its menu and controllers were previously tested on a Steam Frame, and installer components have automated tests. This hotfix and the complete first-install wizard still need fresh-device hardware validation; Steam artwork needs an on-device visual check, and menu music needs a listening check. The executable is unsigned. No game ISO, commercial maps, soundtrack, keys, or game binary is included. Music comes only from the user's local Xbox `ui.map`; compatible native/OpenCE multiplayer is separate from legacy Halo PC/MCC servers.

See the repository README for requirements, SSH steps, controls, sources, and troubleshooting.
