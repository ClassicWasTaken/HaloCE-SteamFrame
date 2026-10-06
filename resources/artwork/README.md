# Halo: Combat Evolved library artwork

`halo-ce-cover.jpg` is the unchanged 1,365 × 2,048 original Halo: Combat
Evolved cover image (312,132 bytes), obtained from
[Halopedia's cover-art record](https://www.halopedia.org/File:HCE_Cover_Art.jpg).
That record credits the [official Halo Facebook post](https://www.facebook.com/Halo/photos/a.137195553028391/1561119617302637/).
The downloaded image URL is
https://www.halopedia.org/images/8/8e/HCE_Cover_Art.jpg.

Halo cover artwork and Halo/Xbox names belong to Microsoft. This promotional
artwork is separate from the installer's MIT-licensed source code; neither this
file nor Halopedia's description grants a general artwork redistribution license.
The installer uses the cover to identify the user's Halo game in Steam. It does
not include game maps, disc images, or a commercial game executable.

`halo-ce-landscape.png` is a 920 × 430 library tile prepared for this installer:
the same cover is scaled to fit a 286 × 430 area without changing its aspect
ratio, alongside a dark green title panel. No generative artwork is used.

`halo-ce-thumbnail.png` is a 180 × 270 aspect-preserving PNG rendition of the same
cover, prepared at build time so the installer's Tk interface can display it
without an additional image-library dependency.

SHA-256:

```text
84fee9349f8f00d8ade44c840330ac54ec4b01ef84086d72b8c791d16c8ad248  halo-ce-cover.jpg
179ff6b9bd1a6ba610e9c0c4b9b32c76e525719b253856d547f65eaa02d1f33d  halo-ce-landscape.png
f9a665a7f0379c7c32943aed10461ef8e16bc809ad59d16df69cab249bba0375  halo-ce-thumbnail.png
```

The installer displays the thumbnail locally and uploads the cover and wide
tile over SSH to fill missing art for the active Steam account's native Halo
shortcut. When Steam is running, its own artwork API writes and verifies the
images; direct `config/grid/` updates require Steam to be already closed.
Portrait artwork uses `<unsigned-shortcut-appid>p.jpg`; the wide tile uses
`<unsigned-shortcut-appid>.png`. Existing custom artwork is preserved, including
an image with a different supported file extension. The same operation runs
for an existing native shortcut and for **Add to Steam again**. New files are
published atomically without replacing an existing file; if publication fails,
only unchanged new files created by that operation are rolled back.

The filename convention was originally compared with the open-source
[steam-shortcut-artwork implementation](https://github.com/pmacoutinho/steam-shortcut-artwork/blob/main/steam-artwork.py),
then the client API and written file hashes were verified on a Frame for 1.2.3.
The 1.3.1 hero, logo, and icon additions have software tests; physical Frame
verification is pending. [Valve's library-asset specifications](https://partner.steamgames.com/doc/store/assets/libraryassets?language=english)
describe the separate banner and transparent logo roles.
## Steam detail-page artwork added in 1.3.1

`halo-ce-hero.jpg` is a 1,920 × 620 JPEG rendition of the original Halo: Combat
Evolved Scorpion/Chief promotional screenshot. The source is
[Halopedia's original press-image record](https://www.halopedia.org/File:HCE_MC_Scorpion.jpg),
which identifies the image as ripped directly from the official **Xbox Imagery,
11 Jan 2002** press CD-ROM, original filename `HI_06_HO.TIF`.
Downloaded original: https://www.halopedia.org/images/6/6c/HCE_MC_Scorpion.jpg.
The installer uses a literal crop `(0, 480, 1920, 1100)` of the 1,920 × 1,440
original and encodes it as a JPEG; it does not stretch or invent image content.
Chief appears on the right, leaving the left side for Steam's separate title
logo overlay. The original is not duplicated in the installer.

`halo-ce-logo.png` is a 1,000 × 431 transparent PNG rendition of the original
Halo: Combat Evolved title logo, resized with its original aspect ratio and alpha
channel. It is obtained from
[Halopedia's title-logo record](https://www.halopedia.org/File:Halo_-_Combat_Evolved_Logo_Huge.png).
Downloaded original: https://www.halopedia.org/images/9/91/Halo_-_Combat_Evolved_Logo_Huge.png.
This record identifies the copyrighted/trademarked CE logo but does not document
an upstream publisher URL. Do not describe this rendition as a newly licensed
asset or the project's own original drawing.

`halo-ce-icon.png` is the exact 256 × 256 PNG rendition of the installer's
existing original Master Chief helmet drawing (`resources/ui/app-icon.svg` and
`app-icon.png`). It is reused as the shortcut icon, separate from the original
game's promotional artwork.

Halo promotional artwork and the Halo/Xbox names and logos belong to Microsoft.
These images identify the user's Halo game in their library. They are separate
from the installer's MIT-licensed source code. Halopedia's descriptions do not
grant a general artwork redistribution license. No game maps, ISO, executable,
or music recording is contained in these assets.

SHA-256 of bundled new files:

```text
3eb9ba1515bd7e25b11a31911edb8610ee33fe9df0505f1a805214e9a9dcff31  halo-ce-hero.jpg
7df3336e9988291552270764e80196b1892ab9d11b79d7d289e6243746d42dc8  halo-ce-logo.png
184620356407e42a33877528c4f14b702df8b026415a99ed16976565fcfbce36  halo-ce-icon.png
```

SHA-256 of separately downloaded originals (kept outside the repository):

```text
e5604c94c66d7a9740b247af4f10ccae674d4c53b44f01a0cec4433b2ca75b21  HCE_MC_Scorpion.jpg
07afdc25f5fe0e11e966ff5e5af2f4adc0196c4ac89b0aeba7df99cc065ab76f  Halo_-_Combat_Evolved_Logo_Huge.png
```

New bundled assets total 944,913 bytes. The optional developer utility
`scripts/generate_library_artwork.py` prepares these renditions with Pillow;
Pillow is not required by the installer at runtime. Source originals and the
three final renditions were visually inspected on 5 October 2026. The hero is
original CE-era art, not Anniversary/MCC or another Halo game's art.
