# Halo Steam Frame Setup 1.1

Download only **[Halo-Steam-Frame-Setup-1.1.0.exe](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/releases/download/v1.1.0/Halo-Steam-Frame-Setup-1.1.0.exe)**. It includes all installer dependencies. No ZIP, Python or extra installer file needed.

Version 1.1 refreshes the guided Windows setup with a modern Apple-inspired interface: a lighter appearance, clearer visual hierarchy, and more space around controls. The sidebar separates **Game data**, **Connect Frame**, and **Install**, with **Back** and **Continue** navigation. Advanced SSH settings and activity details can be expanded when needed; controls and help remain easy to find. The installer still targets the experimental native ARM64/OpenXR Halo CE Steam Frame port.

- Accepts an original Xbox Halo CE ISO/XISO or extracted retail maps supplied by the user.
- Guides Developer Mode/SSH setup, verifies the host fingerprint, and keeps passwords in memory.
- Builds pinned VR source in a rootless Frame container, applies Xbox-style controls and the tutorial head-look fix, and adds the VR game to Steam.
- Prevents duplicate controller input; repairs existing native program files and controls while preserving saves and unrelated settings. Explicit Repair can adopt a validated manual native install in the standard folder.
- Includes source references and third-party notices/source; the installer SHA256 appears below in this release description.

The **[version 1.1.0 source tag](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/tree/v1.1.0)** contains the corresponding installer source, build scripts, and applicable third-party notices/source for rebuilding. GitHub's automatically generated Source code ZIP is optional for developers; users only need the executable linked above.

Validation limitation: the native game was tested on a Frame, and installer components have automated tests. The complete first-install executable still needs fresh-device hardware validation. The executable is unsigned. No game ISO, commercial maps, keys, or game binary is included. Compatible native/OpenCE multiplayer is separate from legacy Halo PC/MCC servers.

See the repository README for requirements, SSH steps, controls, and troubleshooting.
