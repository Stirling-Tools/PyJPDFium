"""Builds a self-contained Linux wheel from a JPDFium checkout's staged natives.

  python tools/build_wheel.py JPDFIUM_CHECKOUT OUT_DIR

1. Copies native/dist/linux-<arch> and runs JPDFium's own native/bundle-runtime-deps.sh on the
   copy, the same closure step and checks its Java natives jar uses. The optional OCR module in
   native/dist/ocr-linux-<arch> joins after, as it is not part of the core bundle.
2. Stages the result with tools/stage_natives.py, so it can share a process with pypdfium2.
3. Collects license texts: JPDFium's, ONNX Runtime's, and the Debian copyright file of every
   system library the bundler copied in.
4. Writes identity.json: revisions, ABI versions, capabilities, pins and every file's digest.
5. Builds the wheel with PYJPDFIUM_BUNDLE_NATIVES=ON and tags it manylinux for the newest glibc
   symbol any bundled file needs.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from stage_natives import sha256, stage_dirs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES = ("runtime.lifecycle", "pdf.open", "pdf.render", "pdf.text", "pdf.raster",
                "image.load", "image.png_write", "image.rectify", "output.transaction",
                "legacy.guards", "text_layer.write", "text_layer.bidi", "text_layer.quad")
OCR_CAPABILITIES = ("ocr.recognize", "ocr.word_geometry")
JPDFIUM_LICENSES = ("PDFIUM-BSD-3.txt", "FREETYPE.txt", "HARFBUZZ.txt", "ICU.txt",
                    "QPDF-APACHE-2.0.txt", "ZLIB.txt", "CLIPPER-BSL-1.0.txt")


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout


def pin(path: Path) -> str:
    return next(line for line in path.read_text().splitlines()
                if line.strip() and not line.startswith("#"))


def bundle(jpdfium: Path, arch_dir: str, work: Path) -> Path:
    dist = work / "native" / "dist" / arch_dir
    shutil.copytree(jpdfium / "native" / "dist" / arch_dir, dist, symlinks=True)
    before = {p.name for p in dist.iterdir()}
    run("bash", str(jpdfium / "native" / "bundle-runtime-deps.sh"), arch_dir, cwd=work)
    added = sorted({p.name for p in dist.iterdir()} - before)
    (work / "bundled-system-libs.txt").write_text("\n".join(added) + "\n", encoding="utf-8")
    return dist


def collect_licenses(jpdfium: Path, staged: Path, system_libs: list[str]) -> list[str]:
    licenses = staged / "licenses"
    licenses.mkdir()
    shutil.copyfile(jpdfium / "NOTICE", licenses / "JPDFIUM-NOTICE.txt")
    shutil.copyfile(jpdfium / "LICENSE", licenses / "JPDFIUM-LICENSE.txt")
    for name in JPDFIUM_LICENSES:
        shutil.copyfile(jpdfium / "native" / "licenses" / name, licenses / name)
    if (staged / "libjpdfium_ocr.so").exists():
        runtime = jpdfium / "native" / "ocr" / "onnxruntime"
        shutil.copyfile(runtime / "LICENSE", licenses / "ONNXRUNTIME-LICENSE.txt")
        shutil.copyfile(runtime / "ThirdPartyNotices.txt", licenses / "ONNXRUNTIME-NOTICES.txt")
    packages = set()
    for lib in system_libs:
        owner = subprocess.run(["dpkg", "-S", f"*/{lib}"], capture_output=True, text=True)
        if owner.returncode != 0:
            raise SystemExit(f"no package owns the bundled library {lib}")
        packages.add(owner.stdout.split(":")[0])
    for package in sorted(packages):
        copyright_file = Path("/usr/share/doc") / package / "copyright"
        if not copyright_file.exists():
            raise SystemExit(f"{package} ships no copyright file")
        shutil.copyfile(copyright_file, licenses / f"{package}.copyright.txt")
    return sorted(p.name for p in licenses.iterdir())


def capabilities(library: Path, function: str, names: tuple[str, ...]) -> dict[str, int]:
    lib = ctypes.CDLL(str(library), mode=ctypes.RTLD_LOCAL)
    query = getattr(lib, function)
    query.argtypes = (ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32))
    levels = {}
    for name in names:
        level = ctypes.c_int32(0)
        query(name.encode(), ctypes.byref(level))
        levels[name] = level.value
    return levels


def api_version(library: Path, function: str) -> str:
    query = getattr(ctypes.CDLL(str(library), mode=ctypes.RTLD_LOCAL), function)
    query.restype = ctypes.c_uint32
    value = query()
    return f"{value >> 16}.{value & 0xFFFF}"


def identity(jpdfium: Path, staged: Path, licenses: list[str], system_libs: list[str]) -> dict:
    manifest = json.loads((staged / "natives-manifest.json").read_text(encoding="utf-8"))
    profiles = {}
    for profile in sorted((jpdfium / "native" / "ocr" / "profiles").glob("*.profile")):
        files = [line.split() for line in profile.read_text().splitlines()
                 if line.startswith(("file ", "derived "))]
        profiles[profile.stem] = {fields[2]: fields[3] for fields in files}
    ocr = staged / "libjpdfium_ocr.so"
    return {
        "pyjpdfium": {"version": _version(), "revision": _git(ROOT, "PYJPDFIUM_REVISION")},
        "jpdfium": {"revision": _git(jpdfium, "JPDFIUM_REVISION"),
                    "api": api_version(staged / "libjpdfium.so", "jpdf_api_version")},
        "platform": {"system": "linux", "machine": platform.machine(),
                     "glibc": platform.libc_ver()[1]},
        "pdfium": pin(jpdfium / "native" / "pdfium.version"),
        "capabilities": capabilities(staged / "libjpdfium.so", "jpdf_capability", CAPABILITIES),
        "ocr": None if not ocr.exists() else {
            "api": api_version(ocr, "jpdf_ocr_api_version"),
            "onnxruntime": pin(jpdfium / "native" / "ocr" / "onnxruntime.version").split()[1],
            "capabilities": capabilities(ocr, "jpdf_ocr_capability", OCR_CAPABILITIES),
            "profiles": profiles,
        },
        "fonts": {"glyphless": "built into libjpdfium.so"},
        "system_libraries": system_libs,
        "licenses": licenses,
        "files": manifest["files"],
        "renames": manifest["renames"],
    }


def _git(path: Path, env: str) -> str:
    """The checkout's commit, or the named variable for exported sources without .git."""
    try:
        return run("git", "-C", str(path), "rev-parse", "HEAD").strip()
    except (OSError, subprocess.CalledProcessError):
        return os.environ.get(env, "unknown")


def _version() -> str:
    text = (ROOT / "src" / "pyjpdfium" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def glibc_floor(paths: list[Path]) -> tuple[int, int]:
    newest = (2, 17)
    for path in paths:
        symbols = run("objdump", "-T", str(path))
        for major, minor in re.findall(r"GLIBC_(\d+)\.(\d+)", symbols):
            newest = max(newest, (int(major), int(minor)))
    return newest


def retag(wheel: Path, tag: str) -> Path:
    """Rewrites the platform tag in the file name and WHEEL, and WHEEL's RECORD line."""
    old_tag = wheel.stem.rsplit("-", 1)[1]
    target = wheel.with_name(wheel.name.replace(f"-{old_tag}.whl", f"-{tag}.whl"))
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(target, "w",
                                                           zipfile.ZIP_DEFLATED) as out:
        names = source.namelist()
        wheel_name = next(n for n in names if n.endswith(".dist-info/WHEEL"))
        record_name = next(n for n in names if n.endswith(".dist-info/RECORD"))
        wheel_text = source.read(wheel_name).decode().replace(f"-{old_tag}\n", f"-{tag}\n")
        digest = base64.urlsafe_b64encode(hashlib.sha256(wheel_text.encode()).digest())
        record = []
        for line in source.read(record_name).decode().splitlines():
            if line.startswith(f"{wheel_name},"):
                line = f"{wheel_name},sha256={digest.rstrip(b'=').decode()},{len(wheel_text)}"
            record.append(line)
        for item in source.infolist():
            if item.filename == wheel_name:
                out.writestr(item, wheel_text)
            elif item.filename == record_name:
                out.writestr(item, "\n".join(record) + "\n")
            else:
                out.writestr(item, source.read(item.filename))
    wheel.unlink()
    return target


def main(jpdfium: Path, out: Path) -> Path:
    arch_dir = {"x86_64": "linux-x64", "aarch64": "linux-arm64"}[platform.machine()]
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pyjpdfium-wheel-") as tmp:
        work = Path(tmp)
        dist = bundle(jpdfium, arch_dir, work)
        system_libs = (work / "bundled-system-libs.txt").read_text().split()
        staged = work / "staged"
        ocr = jpdfium / "native" / "dist" / f"ocr-{arch_dir}"
        stage_dirs([dist, *([ocr] if ocr.is_dir() else [])], staged)
        licenses = collect_licenses(jpdfium, staged, system_libs)
        (staged / "identity.json").write_text(
            json.dumps(identity(jpdfium, staged, licenses, system_libs), indent=2) + "\n",
            encoding="utf-8")
        env = {**os.environ, "JPDFIUM_NATIVE_DIR": str(staged), "PYJPDFIUM_BUNDLE_NATIVES": "ON",
               "JPDFIUM_INCLUDE_DIR": str(jpdfium / "native" / "bridge" / "include"),
               "JPDFIUM_OCR_INCLUDE_DIR": str(jpdfium / "native" / "ocr" / "include")}
        built = Path(tmp) / "wheel"
        # A fresh CMake directory, so no cached library path from a dev build leaks in.
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps",
                        "-C", f"build-dir={work / 'cmake'}", str(ROOT), "-w", str(built)],
                       env=env, check=True)
        wheel = next(built.glob("pyjpdfium-*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            unpacked = Path(tmp) / "unpacked"
            archive.extractall(unpacked)
        elves = [p for p in unpacked.rglob("*.so*") if p.is_file()]
        major, minor = glibc_floor(elves)
        tagged = retag(wheel, f"manylinux_{major}_{minor}_{platform.machine()}")
        final = out / tagged.name
        shutil.move(tagged, final)
    print(f"{final} ({final.stat().st_size / 2**20:.1f} MiB), sha256 {sha256(final)}")
    return final


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
