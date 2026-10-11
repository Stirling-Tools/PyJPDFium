"""Stages JPDFium's natives for Python, so they can share a process with other Python packages.

  python tools/stage_natives.py JPDFIUM_DIST DEST

OCRmyPDF imports pypdfium2, whose libpdfium.so carries the soname of JPDFium's PDFium, and
onnxruntime wheels ship libonnxruntime.so.1. The dynamic linker binds a dependency to a loaded
library with the same soname, so JPDFium's core would call into another PDFium. Staging gives
our copies their own sonames, points RUNPATH at the staging directory only, and writes
natives-manifest.json with every file's digest before and after. Linux only; needs patchelf.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

RENAMES = {
    "libpdfium.so": "libjpdfium_pdfium.so",
    "libonnxruntime.so.1": "libjpdfium_onnxruntime.so.1",
}
MANIFEST = "natives-manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def patchelf(*args: str) -> str:
    done = subprocess.run(["patchelf", *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def is_elf(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) == b"\x7fELF"


def stage(source: Path, dest: Path) -> dict:
    if not sys.platform.startswith("linux"):
        raise SystemExit("stage_natives.py stages Linux natives only")
    if shutil.which("patchelf") is None:
        raise SystemExit("patchelf is required")
    if dest.exists():
        raise SystemExit(f"{dest} exists; stage into a new directory")
    dest.mkdir(parents=True)
    staged: dict[str, Path] = {}
    origins: dict[str, Path] = {}
    # Real files only, each under its soname, so no symlink is needed after staging.
    for path in sorted(source.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        name = path.name
        if is_elf(path):
            try:
                name = patchelf("--print-soname", str(path)) or name
            except subprocess.CalledProcessError:
                pass  # no DT_SONAME: keep the file name
        name = RENAMES.get(name, name)
        if name in staged:
            raise SystemExit(f"two files stage as {name}")
        target = dest / name
        shutil.copy2(path, target)
        staged[name], origins[name] = target, path
    for name, target in staged.items():
        if not is_elf(target):
            continue
        if target.name in RENAMES.values():
            patchelf("--set-soname", target.name, str(target))
        for needed in patchelf("--print-needed", str(target)).split():
            if needed in RENAMES:
                patchelf("--replace-needed", needed, RENAMES[needed], str(target))
        patchelf("--set-rpath", "$ORIGIN", str(target))
    entries = []
    for name, target in sorted(staged.items()):
        if is_elf(target):
            needed = patchelf("--print-needed", str(target)).split()
            stale = sorted(set(needed) & set(RENAMES))
            if stale:
                raise SystemExit(f"{name} still needs {stale}")
        entries.append({
            "name": name,
            "sha256": sha256(target),
            "source": origins[name].name,
            "source_sha256": sha256(origins[name]),
        })
    manifest = {"source": str(source.resolve()), "renames": RENAMES, "files": entries}
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    result = stage(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"staged {len(result['files'])} files into {sys.argv[2]}")
