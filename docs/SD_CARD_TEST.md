# SD-card installer test

This private Windows test installer adds **Internal storage / SD card** selection and a fix for menus opening behind or beside you. GitHub's public release stays at 1.4.1 until the test is approved.

1. Insert a card that is already prepared and mounted on your Frame with an executable ext4 or f2fs filesystem and at least 12 GiB free.
2. Choose your original Xbox Halo CE image for a new SD installation.
3. On **Connect Frame**, enter your connection details and click **Refresh storage** or **Test connection**.
4. Select **SD card** and choose the detected card. Check its free space and the destination shown before continuing.
5. Install, then launch **Halo: Combat Evolved VR (Native, SD card)** from Steam.

The game, maps, new campaign saves, installation workspace and installer backups use the selected card. Steam artwork and Notes stay with your Steam account. Podman may still need temporary space on internal storage for its compiler container.

**Repair** and **Uninstall** use the location you select. They do not move or delete an internal copy. A new SD installation has its own saves; this test does not automatically migrate campaigns between drives. To remove an old internal copy after testing, select **Internal storage**, then **Uninstall** with **Keep saves** checked.

If the card is missing or changed, refresh storage and select it again. Setup rejects unmounted, read-only or non-executable cards instead of falling back to the internal drive. It does not format or mount cards for you. Cards using FAT/exFAT need to be prepared with a supported Linux filesystem before this installer can run native programs on them; formatting erases card contents, so keep any files you need first.

Menus use your current headset position and gaze when they open, then stay in place while open. Try opening the pause menu after walking or turning 90°/180°, close it, turn again, and reopen. Check controller navigation and clicking as well as placement; recentering should deliberately place the open menu in front again.

Detection reads the actual Linux mount and SD-device metadata rather than guessing from a folder name. The first test still needs confirmation on a physical Frame: detection, installation, launch, repair, removal with retained saves, and the new menu placement.

Implementation references: [Linux mountinfo format](https://www.man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html), [Linux SD/MMC device attributes](https://www.kernel.org/doc/html/latest/driver-api/mmc/mmc-dev-attrs.html), [Valve's Steam Frame specifications](https://store.steampowered.com/hardware/steamframe).
