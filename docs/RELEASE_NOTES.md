# Halo Steam Frame Setup 1.2

Download only **[Halo-Steam-Frame-Setup-1.2.0.exe](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/releases/download/v1.2.0/Halo-Steam-Frame-Setup-1.2.0.exe)**. It includes all installer dependencies. No ZIP, Python or extra installer file needed.

Version 1.2 gives the guided Windows setup a modern retro original Xbox dashboard appearance: dark gunmetal panels, luminous green accents, a circular core, and beveled menus. The guided **Game data**, **Connect Frame**, and **Install Halo VR** steps retain **Back** and **Continue** navigation. Advanced SSH settings and activity details can be expanded when needed; controls and help remain easy to find. The installer still targets the experimental native ARM64/OpenXR Halo CE Steam Frame port.

- Accepts an original Xbox Halo CE ISO/XISO or extracted retail maps supplied by the user.
- Identifies the Windows executable with a project-drawn Master Chief helmet icon in olive armor and a gold visor.
- Guides Developer Mode/SSH setup, verifies the host fingerprint, and keeps passwords in memory.
- Builds pinned VR source in a rootless Frame container, applies Xbox-style controls and the tutorial head-look fix, and adds the VR game to Steam.
- Displays the original Halo CE cover inside the installer and automatically adds portrait and landscape library artwork for the native shortcut, including during repair and **Add to Steam again**, while preserving custom artwork.
- Quietly loops the original Halo menu music after selecting valid local Xbox data, with a louder 12% sample-amplitude default and a visible mute toggle. The loop comes from the user's own `ui.map`; no soundtrack is bundled, downloaded, or uploaded. Repair using only remote maps has no music preview.
- Prevents duplicate controller input; repairs existing native program files and controls while preserving saves and unrelated settings. Explicit Repair can adopt a validated manual native install in the standard folder.
- Includes source references and third-party notices/source; the installer SHA256 appears below in this release description.

The **[version 1.2.0 source tag](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/tree/v1.2.0)** contains the corresponding installer source, build scripts, and applicable third-party notices/source for rebuilding. GitHub's automatically generated Source code ZIP is optional for developers; users only need the executable linked above.

Validation limitation: the native game was tested on a Frame, and installer components have automated tests. The complete first-install executable still needs fresh-device hardware validation; the new artwork needs an on-device visual check, and menu audio still needs a listening check. The executable is unsigned. No game ISO, commercial maps, soundtrack, keys, or game binary is included. Compatible native/OpenCE multiplayer is separate from legacy Halo PC/MCC servers.

See the repository README for requirements, SSH steps, controls, and troubleshooting.
