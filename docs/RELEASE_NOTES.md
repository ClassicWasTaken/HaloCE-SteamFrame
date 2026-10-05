# Halo Steam Frame Setup 1.0

Download **HaloFrameSetup.exe** from this release's Assets to run the compiled Windows installer. Python and SSH dependencies are included; no separate installation is needed.

Guided Windows setup for the experimental native ARM64/OpenXR Halo CE Steam Frame port.

- Accepts an original Xbox Halo CE ISO/XISO or extracted retail maps supplied by the user.
- Guides Developer Mode/SSH setup, verifies the host fingerprint, and keeps passwords in memory.
- Builds pinned VR source in a rootless Frame container, applies Xbox-style controls and the tutorial head-look fix, and adds the VR game to Steam.
- Prevents duplicate controller input; repairs existing native program files and controls while preserving saves and unrelated settings. Explicit Repair can adopt a validated manual native install in the standard folder.
- Includes source references, third-party notices/source, and SHA256 checksums.

**HaloFrameSetup-1.0.0-source.zip** contains corresponding installer source and notices for rebuilding. **SHA256SUMS.txt** contains checksums for both downloads.

Validation limitation: the native game was tested on a Frame, and installer components have automated tests. The complete first-install executable still needs fresh-device hardware validation. The executable is unsigned. No game ISO, commercial maps, keys, or game binary is included. Compatible native/OpenCE multiplayer is separate from legacy Halo PC/MCC servers.

See the repository README for requirements, SSH steps, controls, and troubleshooting.
