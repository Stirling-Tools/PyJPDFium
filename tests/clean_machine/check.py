"""Checks an installed wheel on a clean machine: no compiler, no PDF, image or ICU libraries
from the system, no network, no PYJPDFIUM_NATIVE_DIR. Exits non-zero at the first failure.

  python check.py              # PYJPDFIUM_OCR_PROFILE names a fetched profile directory

Runs the pyjpdfium command, renders, recognizes, writes a text layer, runs OCRmyPDF with the
plugin when OCRmyPDF is installed, and audits every native library the process loaded.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

LINES = ["Clean machine check", "invoice 4821 paid"]


def step(name: str) -> None:
    print(f"--- {name}", flush=True)


def run(*command: str) -> str:
    done = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if done.returncode != 0:
        raise SystemExit(f"FAILED {' '.join(command)}\n{done.stdout}\n{done.stderr}")
    return done.stdout


def pdf(pages: list[tuple[str, str, bytes | None]]) -> bytes:
    """Pages of (page dictionary extras, content, optional /Im0 image object)."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for extra, content, image in pages:
        number = len(objects) + 1
        kids.append(f"{number} 0 R")
        resources = f"/Resources << /XObject << /Im0 {number + 2} 0 R >> >>" if image else ""
        objects.append(f"<< /Type /Page /Parent 2 0 R {extra} {resources} "
                       f"/Contents {number + 1} 0 R >>".encode())
        data = content.encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
        if image:
            objects.append(image)
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out, offsets = bytearray(b"%PDF-1.7\n"), []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1,
                                                                               xref)
    return bytes(out)


def text_page() -> tuple[str, str, None]:
    font = "/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>"
    content = "".join(f"BT /F1 26 Tf 72 {700 - 60 * i} Td ({line}) Tj ET "
                      for i, line in enumerate(LINES))
    return f"/MediaBox [0 0 612 792] {font}", content, None


def main() -> None:
    import pyjpdfium

    if os.environ.get("PYJPDFIUM_NATIVE_DIR"):
        raise SystemExit("unset PYJPDFIUM_NATIVE_DIR: the check is of the bundled natives")
    work = Path(tempfile.mkdtemp(prefix="clean-"))
    scripts = Path(sys.executable).parent
    libs = (Path(pyjpdfium.__file__).parent / "_libs").resolve()
    expected = " ".join(LINES)

    step("pyjpdfium doctor")
    report = run(str(scripts / "pyjpdfium"), "doctor")
    print(report)
    if "0 problem(s)" not in report or "match natives-manifest.json" not in report:
        raise SystemExit("doctor found problems")

    step("render, text and OCR in this process")
    source = work / "text.pdf"
    source.write_bytes(pdf([text_page()]))
    with pyjpdfium.open_document(source) as document, document.page(0) as page:
        assert " ".join(page.text().split()) == expected, page.text()
    png = work / "page.png"
    pyjpdfium.rasterize_page(source, 0, png, device="pnggray", raster_dpi=300)
    with pyjpdfium.OcrEngine(os.environ["PYJPDFIUM_OCR_PROFILE"]) as engine:
        result = engine.recognize(png)
    assert [line.text for line in result.lines] == LINES, result.text
    layer = work / "layer.pdf"
    pyjpdfium.write_text_layer(layer, result.text_lines(), image_size=result.image_size,
                               dpi=result.dpi)
    with pyjpdfium.open_document(layer) as document, document.page(0) as page:
        assert " ".join(page.text().split()) == expected

    step("every native library this process loaded")
    system = ("libc.so", "libm.so", "libstdc++.so", "libgcc_s.so", "ld-linux", "libpthread.so",
              "libdl.so", "librt.so")
    stray = []
    for line in Path("/proc/self/maps").read_text().splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 6 or ".so" not in parts[5]:
            continue
        path = Path(os.path.realpath(parts[5]))
        if path.is_relative_to(libs) or path.name.startswith(system):
            continue
        stdlib = Path(sys.base_prefix, "lib", f"python{sys.version_info[0]}.{sys.version_info[1]}")
        if any(path.is_relative_to(p.resolve()) for p in (Path(sys.prefix), stdlib)):
            continue  # the venv's packages and the standard library's extension modules
        if "python3" in path.name:
            continue  # the interpreter
        stray.append(str(path))
    print("\n".join(sorted(set(stray))) or "(none outside the wheel and the C runtime)")
    allowed = ("libz.so", "libexpat.so", "libffi.so", "libbz2.so", "liblzma.so", "libcrypto.so",
               "libssl.so", "libuuid.so", "libmpdec.so", "libsqlite3.so", "libtinfo.so",
               "libreadline.so", "libncursesw.so")  # loaded by Python's standard library
    unexpected = [p for p in set(stray) if not Path(p).name.startswith(allowed)]
    if unexpected:
        raise SystemExit(f"native libraries loaded from the system: {sorted(unexpected)}")

    if importlib.util.find_spec("ocrmypdf") is None:
        step("OCRmyPDF is not installed; plugin check skipped")
        return
    step("OCRmyPDF with the pyjpdfium plugin")
    scan_png = work / "scan.png"
    pyjpdfium.rasterize_page(source, 0, scan_png, device="pnggray", raster_dpi=300)
    with pyjpdfium.load_image(scan_png) as bitmap:
        gray = bitmap.tobytes()[0::3] if bitmap.pixel_format.name == "RGB8" else bitmap.tobytes()
        width, height = bitmap.width, bitmap.height
    data = zlib.compress(gray)
    image = (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
             b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n"
             % (width, height, len(data)) + data + b"\nendstream")
    scanned = work / "scanned.pdf"
    scanned.write_bytes(pdf([("/MediaBox [0 0 612 792]", "q 612 0 0 792 0 0 cm /Im0 Do Q",
                              image)]))
    out = work / "ocr.pdf"
    run(sys.executable, "-m", "ocrmypdf", "--plugin", "pyjpdfium.ocrmypdf", "--output-type",
        "pdf", str(scanned), str(out))
    with pyjpdfium.open_document(out) as document, document.page(0) as page:
        assert " ".join(page.text().split()) == expected, page.text()
    print("OCRmyPDF output reads:", expected)


if __name__ == "__main__":
    main()
    print("clean machine check passed")
