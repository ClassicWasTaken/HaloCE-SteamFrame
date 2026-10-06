# Halo Steam Frame Setup 1.3.1

Download only **[DOWNLOAD THIS FILE — Halo-Steam-Frame-Setup-1.3.1.exe](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/releases/download/v1.3.1/Halo-Steam-Frame-Setup-1.3.1.exe)**. This is the complete Windows installer, including USB tools and library artwork; no separate ZIP or Python installation is needed.

This patch fills out the native Halo non-Steam library entry with an original Halo CE banner, transparent title logo, cover images, and a Master Chief shortcut icon. It adds a game description and Xbox-style control guide in **Steam Notes**. Steam's non-Steam shortcuts do not expose an editable store-style About description: the patch uses the existing Notes feature instead of claiming a store page, achievements, reviews, or another game's Steam identity.

Already installed? Choose **Steam info**, connect by USB-C or Wi-Fi/Ethernet, and click **Update Steam info**. This verifies the existing native game and updates its library information without reinstalling or compiling it, uploading maps, or requiring another ISO. Steam Home and SteamVR stay running.

- Adds missing cover, landscape tile, hero/banner and transparent logo through the running Steam client, or safe library-file registration when Steam is already closed. Custom artwork is preserved.
- Stores the shortcut icon in the owned native game folder and uses Steam's shortcut-icon interface. Existing custom icons are kept. If the icon's saved shortcut identity cannot be verified, setup shows a retry/manual step instead of guessing.
- Adds one private **Halo CE VR — About & controls** note using Steam's native Notes interface. Existing notes and edits are preserved. Notes use Steam's normal synchronization; if the feature is unavailable or sync cannot be verified, setup provides text to copy manually.
- Checks the active Steam account and exact native executable before library changes. Unavailable or unverified artwork, icon, or Notes updates are reported separately from the installed game's status.
- Retains Xbox controls, original Xbox data validation, tutorial changes, USB transfer, left-to-right progress, redacted logs, save-preserving repair and uninstall, and the Steam Home session safeguard.
- Refreshes the GitHub README with Halo banner, logo, and helmet artwork and a prominent single-file download link.

The new bundled artwork adds less than 1 MB. Hero and logo provenance and file hashes are recorded in the [artwork notice](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/blob/v1.3.1/resources/artwork/README.md). Promotional artwork remains separate from the project's MIT code license.

**Validation limits:** the additional artwork, icon, and Notes paths have software tests; their appearance and Notes behavior still need verification on a real Steam Frame. The native game, Xbox controls, and earlier cover-art registration were previously checked on one Frame. Direct USB transfer, a fresh first install, and full game uninstall remain unverified on physical hardware. The upstream ARM64/OpenXR port is experimental. The Frame still needs internet for source and compiler downloads during installation; a Steam-info-only update does not build the game.

Use your own authorized original **Xbox** Halo CE data for game installation. USA Rev 2 is validated; other retail revisions are accepted only when their actual map headers match the supported builds. PC, Xbox 360 Anniversary, MCC and Quest inputs remain unsupported. No ISO, game maps, commercial executable, keys or soundtrack is bundled.

The [source tag](https://github.com/ClassicWasTaken/HaloCE-SteamFrame/tree/v1.3.1) includes the installer source, build scripts and third-party notices. The release attaches one clearly labeled EXE and prints its SHA256 here. The EXE is unsigned.

Sources: [Valve's library artwork guide](https://partner.steamgames.com/doc/store/assets/libraryassets?language=english), [Valve's Notes announcement](https://store.steampowered.com/news/app/593110/view/3687931965598906184), [Valve's Frame USB/SSH guide](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging), and the [full acknowledgements](SOURCES.md).
