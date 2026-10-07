# Install Halo VR on an SD card

Version 1.4.2 adds **Internal storage / SD card** selection. [Download the Windows installer](https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/download/v1.4.2/Halo-Steam-Frame-Mod-Setup-1.4.2.exe) and [verify release provenance](BUILD_PROVENANCE.md).

1. Insert a card that is already prepared and mounted on your Frame with an executable ext4 or f2fs filesystem and at least 12 GiB free.
2. Choose your original Xbox Halo CE image for a new SD installation.
3. On **Connect Frame**, enter your connection details and click **Refresh storage** or **Test connection**.
4. Select **SD card** and choose the detected card. Check its free space and the destination shown before continuing.
5. Install, then launch **Halo: Combat Evolved VR (Native, SD card)** from Steam.

The game, maps, new campaign saves, installation workspace and installer backups use the selected card. Steam artwork and Notes stay with your Steam account. Podman may still need temporary space on internal storage for its compiler container.

**Install, Repair and Uninstall** use the location you select. An SD operation keeps the internal copy. A new SD installation starts its own profiles and campaign saves in `save-v1.4`; setup does not automatically migrate campaigns between drives. Repair keeps existing 1.4.x saves at that selected location. To remove an old internal copy, select **Internal storage**, then **Uninstall** with **Keep saves** checked. Retained save backups stay beside the selected game folder, on that same drive.

If the card is missing or changed, refresh storage and select it again. Setup rejects unmounted, read-only or non-executable cards instead of falling back to the internal drive. It does not format or mount cards for you. Cards using FAT/exFAT need to be prepared with a supported Linux filesystem before this installer can run native programs on them; formatting erases card contents, so keep any files you need first.

Menus use your current headset position and gaze when they open, then stay in place while open. Try opening the pause menu after walking or turning 90°/180°, close it, turn again, and reopen. Check controller navigation and clicking as well as placement; recentering should deliberately place the open menu in front again.

Detection checks Linux mount and physical SD-device metadata. A returning card can be repaired or uninstalled after a normal remount at the same path; a mount change during an operation stops it. Refresh storage after reconnecting. A renamed mount path is not automatically adopted.

The user confirmed SD installation and menu placement on their Frame using the private build. Measured performance and a complete repair/uninstall or multiplayer test matrix were not supplied.

[Setup and co-op](SETUP.md) · [Release notes](RELEASE_NOTES.md)

Implementation references: [Linux mountinfo format](https://www.man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html), [Linux SD/MMC device attributes](https://www.kernel.org/doc/html/latest/driver-api/mmc/mmc-dev-attrs.html), [Valve's Steam Frame specifications](https://store.steampowered.com/hardware/steamframe).
