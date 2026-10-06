"""Prepare small Steam artwork renditions from separately obtained originals.

Requires Pillow only when regenerating these checked-in assets. The installer
does not download artwork or need Pillow at runtime. Original source attribution
is recorded in resources/artwork/README.md; originals are not duplicated in the
executable. No generative artwork is used.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hero-original", type=Path, required=True)
    parser.add_argument("--logo-original", type=Path, required=True)
    args = parser.parse_args()
    originals = (
        (args.hero_original,
         "e5604c94c66d7a9740b247af4f10ccae674d4c53b44f01a0cec4433b2ca75b21"),
        (args.logo_original,
         "07afdc25f5fe0e11e966ff5e5af2f4adc0196c4ac89b0aeba7df99cc065ab76f"),
    )
    for path, expected in originals:
        if sha256(path) != expected:
            raise ValueError(f"Original source checksum differs: {path.name}")
    repo = Path(__file__).resolve().parents[1]
    destination = repo / "resources" / "artwork"
    destination.mkdir(parents=True, exist_ok=True)

    # Literal, unscaled crop of the original CE press image. This includes the
    # Chief's helmet and upper body at right, leaving the tank at left for
    # Steam's separate transparent title overlay.
    with Image.open(args.hero_original) as source:
        if source.size != (1920, 1440) or source.mode != "RGB":
            raise ValueError("Expected the original 1920x1440 RGB Scorpion image")
        hero = source.crop((0, 480, 1920, 1100))
        hero.save(destination / "halo-ce-hero.jpg", quality=91, optimize=True,
                  progressive=True, subsampling=0)

    with Image.open(args.logo_original) as source:
        if source.size != (2459, 1061) or source.mode != "RGBA":
            raise ValueError("Expected the original 2459x1061 RGBA CE title logo")
        if source.getchannel("A").getextrema() != (0, 255):
            raise ValueError("The title logo must retain its transparent background")
        logo = source.resize((1000, 431), Image.Resampling.LANCZOS)
        logo.save(destination / "halo-ce-logo.png", optimize=True)

    # The library's original project drawing is independent of the Windows
    # installer icon. Retain the checked-in rendition instead of copying a
    # replacement installer icon into existing Steam library artwork.
    if sha256(destination / "halo-ce-icon.png") != "184620356407e42a33877528c4f14b702df8b026415a99ed16976565fcfbce36":
        raise ValueError("The existing project-drawn Steam shortcut icon differs")
    for name in ("halo-ce-hero.jpg", "halo-ce-logo.png", "halo-ce-icon.png"):
        path = destination / name
        with Image.open(path) as image:
            print(f"{sha256(path)}  {name}  {image.width}x{image.height} "
                  f"{image.mode}  {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
