"""Build installer executable/source without disc images, maps or private files."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION = "1.4.3"
EXE_NAME = f"Halo-Steam-Frame-Mod-Setup-{VERSION}.exe"

def allowed_source_files():
    roots = [ROOT / name for name in ("src", "resources", "docs", "scripts", "tests", ".github")]
    files = [ROOT / name for name in ("README.md", "LICENSE", "SECURITY.md", "pyproject.toml", ".gitignore", ".gitattributes")]
    for directory in roots:
        if directory.exists():
            for path in directory.rglob("*"):
                if path.is_file() and not any(part in ("__pycache__", ".pytest_cache") or part.endswith(".egg-info") for part in path.parts):
                    files.append(path)
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError("Unexpected release source path")
        if path.suffix.lower() in (".iso", ".xiso", ".map", ".wav", ".mp3", ".ogg", ".wma", ".reg", ".key", ".pem") or path.name in ("halo", "hosts.json"):
            raise RuntimeError("Private or commercial files must never be packaged")
    return sorted(files)

def main():
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows.")
    DIST.mkdir(exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/bundle_usb_tools.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/gather_notices.py"), "--download-sources"], cwd=ROOT, check=True)
    source_files = allowed_source_files()
    snapshots = {path:hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    subprocess.run([sys.executable,"-m","PyInstaller","--noconfirm","--clean","--onefile","--windowed",
        "--name",Path(EXE_NAME).stem,"--icon",str(ROOT / "resources/ui/app-icon.ico"),"--paths",str(ROOT / "src"),
        "--add-data",str(ROOT / "resources") + ";resources",
        "--add-data",str(ROOT / "docs") + ";docs",
        "--add-data",str(ROOT / "LICENSE") + ";.",
        "--distpath",str(DIST),"--workpath",str(ROOT / "build/pyinstaller"),
        "--specpath",str(ROOT / "build"),str(ROOT / "scripts/launch.py")], cwd=ROOT, check=True)
    source = DIST / f"HaloFrameSetup-{VERSION}-source.zip"
    if source_files != allowed_source_files() or any(hashlib.sha256(path.read_bytes()).hexdigest() != expected for path,expected in snapshots.items()):
        raise RuntimeError('Source changed during the executable build. Rebuild the release from a stable checkout.')
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files:
            archive.write(path, f"halo-steam-frame-installer-{VERSION}/" + path.relative_to(ROOT).as_posix())
    files = [DIST / EXE_NAME, source]
    checksums = []
    for path in files:
        checksums.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
    (DIST / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(json.dumps({'releaseFiles':[path.name for path in files] + ['SHA256SUMS.txt'], 'version':VERSION}))

if __name__ == "__main__":
    main()
