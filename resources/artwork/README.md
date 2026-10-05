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

The installer bundles all three files in its executable. It displays the
thumbnail locally, uploads the cover and wide tile over SSH, and fills missing
artwork in the active Steam account's `config/grid/` directory.
Portrait artwork uses `<unsigned-shortcut-appid>p.jpg`; the wide tile uses
`<unsigned-shortcut-appid>.png`. Existing custom artwork is preserved, including
an image with a different supported file extension. The same operation runs
for an existing native shortcut and for **Add to Steam again**. New files are
published atomically without replacing an existing file; if publication fails,
only unchanged new files created by that operation are rolled back.

The filename convention was checked against the open-source
[steam-shortcut-artwork implementation](https://github.com/pmacoutinho/steam-shortcut-artwork/blob/main/steam-artwork.py).
Artwork registration is covered by local filesystem tests. It has not yet been
verified on a physical Steam Frame.
