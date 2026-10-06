<p align="center">
  <img src="resources/artwork/halo-ce-hero.jpg" alt="Halo: Combat Evolved — Master Chief in battle" width="800">
</p>

<p align="center">
  <img src="resources/artwork/halo-ce-logo.png" alt="Halo: Combat Evolved" width="180">
</p>

**Halo CE Steam Frame VR Mod — 1.4.0**

[**Download Halo-Steam-Frame-Mod-Setup-1.4.0.exe**](https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/download/v1.4.0/Halo-Steam-Frame-Mod-Setup-1.4.0.exe) for Windows 10/11 x64. Run this one file; Python, an installer ZIP, and a separate USB tools download are unnecessary. [Release notes & SHA256 checksum](https://github.com/ClassicWasTaken/HaloSteamFrameMod/releases/tag/v1.4.0) · [1.4.0 source](https://github.com/ClassicWasTaken/HaloSteamFrameMod/tree/v1.4.0).

Play native ARM64/OpenXR Halo CE with **LAN and online campaign co-op**, **head-directed walking**, and Xbox-style buttons. Aim with the right controller; the reticle follows the nominal shot trajectory at render rate. Stereo sun glow defaults to half intensity. The headset tester confirmed reticle motion and LAN/online campaign co-op work with the engine patch used by this release. Measured performance and distant-peer coverage have not been reported.

<p align="center">
  <img src="docs/images/halocevr-steam-frame-example.jpeg" alt="Halo CE VR gameplay example with tracked hands and a plasma rifle beneath Halo's night sky" width="800">
</p>

*Community VR example by [u/Sea-Communication760](https://www.reddit.com/r/virtualreality/comments/1wpvi8n/halo_halocevr_working_great_on_steam_frame/): PC HaloCEVR on Steam Frame through Proton ARM. This is not a native 1.4.0 capture.*

Supply your own authorized **original Xbox Halo CE ISO/XISO or extracted maps**. USA Rev 2 was validated with the stable installer; PC, Xbox 360 Anniversary, and MCC data are unsupported. No retail executable, disc image, maps, product keys, or soundtrack is included or downloaded. Halo artwork and licensed components retain their rights and notices.

Choose **Install**, select your data, and follow the USB-C or network SSH guide. Setup adds Steam artwork and Notes automatically. The first build on the Frame can take tens of minutes.

1.4.0 **replaces 1.3.5 in place** at `~/Games/HaloCENativeVR`, keeping **Halo: Combat Evolved VR (Native)** in Steam. **Install** recognizes a verified 1.3.5 installation and rebuilds it; **Repair** also upgrades it. Verified Xbox maps can be reused without an ISO. Old saves remain unchanged; the new engine uses `save-v1.4` and requires a new profile/campaign because older checkpoints are incompatible. Campaign has one player per machine, with LAN, Internet, and invite joining. Peers need matching **protocol 17** builds; 1.3.5 protocol 11 cannot join.

[Setup](docs/SETUP.md) · [Controls](docs/CONTROLS.md) · [Release notes](docs/RELEASE_NOTES.md) · [Sources](docs/SOURCES.md) · [Third-party notices](docs/THIRD_PARTY.md)
