# Classic Halo PC installer icon

Version 1.3.2 uses the classic Halo: Combat Evolved PC helmet-and-shoulders
application icon requested by the user. The clean image contains no desktop
background, shortcut arrow, or filename label.

`app-icon.ico` is the unchanged 29,926-byte icon downloaded from
[HaloNet's favicon](https://halonet.net/favicon.ico) on 5 October 2026. It was
verified byte-for-byte against icon group 102 reconstructed from the locally
installed retail Halo PC `halo.exe`. No game executable was copied into this
repository or the installer. The ICO contains the original 16, 24, 32, and 48
pixel images at 4, 8, and 32-bit color: 12 entries in total.

`app-icon.png` is an unchanged-pixel PNG export of the ICO's 48 × 48, 32-bit
RGBA frame for the installer's Tk window icon. It retains transparency. No
resizing, redrawing, or generative image processing was applied. Larger Windows
display sizes use the original available artwork; this is not an HD remake.

SHA256:

```text
aa212eba758abaad8e7a134c4084110c9311ded77c0924865294d7ecf26f0216  app-icon.ico
e92525343f2e88f57024a34a1eda22f4de0dfbb16c5fcc9b16c7a1ba298b1ab9  app-icon.png
```

Halo artwork, Master Chief, and associated names and trademarks retain their
rights holders' rights, including Microsoft. The icon is separate from the
installer code's MIT license; hosting and attribution do not grant a general
artwork redistribution license.

The earlier project-drawn helmet remains the Steam shortcut icon, under
`resources/artwork/halo-ce-icon.png` with its original vector source
`halo-ce-icon.svg`. Changing the Windows installer icon does not replace
existing Steam library icons.
