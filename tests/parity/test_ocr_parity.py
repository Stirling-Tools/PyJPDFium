"""OCR parity with the official PaddleOCR 3.7 pipeline on the same PNG files.

Opt-in: set PYJPDFIUM_OCR_PROFILE to a profile fetched with JPDFium's fetch_profile.py and
PYJPDFIUM_OCR_REFERENCE to a Python with paddleocr 3.7.0 and onnxruntime 1.30.0 (see
tests/parity/ocr-requirements.txt). The reference runs in its own process and never downloads.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import pyjpdfium

PROFILE = os.environ.get("PYJPDFIUM_OCR_PROFILE")
REFERENCE = os.environ.get("PYJPDFIUM_OCR_REFERENCE")
RUNNER = Path(__file__).with_name("ocr_reference_runner.py")
pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(not (PROFILE and REFERENCE),
                       reason="PYJPDFIUM_OCR_PROFILE and PYJPDFIUM_OCR_REFERENCE are not set"),
]

FONTS = ("/Resources << /Font << "
         "/F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> "
         "/F2 << /Type /Font /Subtype /Type1 /BaseFont /Times-Roman /Encoding /WinAnsiEncoding >> "
         "/F3 << /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >> "
         "/F4 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
         "/Encoding /WinAnsiEncoding >> >> >>")

PAGES = {
    "letters": ("/MediaBox [0 0 612 792]",
                "BT /F1 16 Tf 72 720 Td (The quick brown fox jumps over the lazy dog.) Tj ET "
                "BT /F2 14 Tf 72 690 Td (Pack my box with five dozen liquor jugs.) Tj ET "
                "BT /F3 12 Tf 72 660 Td (Invoice No. 2026-0042   Total: 1,234.56 EUR) Tj ET "
                "BT /F4 20 Tf 72 620 Td (Grand total due) Tj ET "
                "BT /F1 11 Tf 72 590 Td (Caf\\351 na\\357ve r\\351sum\\351 \\374ber Stra\\337e) Tj ET"),
    "columns": ("/MediaBox [0 0 612 792]",
                "".join(f"BT /F1 12 Tf {x} {700 - 24 * row} Td ({cell}) Tj ET "
                        for row, cells in enumerate([("Item", "Qty", "Price"),
                                                     ("Paper A4", "12", "4.99"),
                                                     ("Toner", "2", "61.20"),
                                                     ("Stapler", "1", "8.75")])
                        for x, cell in zip((72, 300, 450), cells))),
    "rotated": ("/MediaBox [0 0 612 792]",
                "BT /F1 16 Tf 0 1 -1 0 300 200 Tm (Vertical heading text) Tj ET "
                "BT /F1 14 Tf 72 720 Td (A horizontal line beside it) Tj ET"),
    "skewed": ("/MediaBox [0 0 612 792]",
               "BT /F1 18 Tf 0.99863 0.05234 -0.05234 0.99863 72 500 Tm "
               "(A slightly skewed line of text) Tj ET"),
    "tiny": ("/MediaBox [0 0 150 30]", "BT /F1 14 Tf 5 10 Td (Tiny label) Tj ET"),
}

CASES = [
    ("letters", "pnggray", 300),
    ("letters", "png16m", 200),
    ("letters", "pngmono", 300),
    ("letters", "pnggray", 600),  # 5100 x 6600: the detector scales it under 4000 px
    ("columns", "pnggray", 300),
    ("rotated", "pnggray", 300),
    ("skewed", "png16m", 300),
    ("tiny", "pnggray", 72),  # 150 x 30: upscaled to the 64 px minimum side
]


def write_pdf(path: Path, page_extra: str, content: str) -> Path:
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R {page_extra} {FONTS} /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    out, offsets = bytearray(b"%PDF-1.7\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += b"xref\n0 5\n0000000000 65535 f \n"
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


@pytest.fixture(scope="module")
def images(tmp_path_factory) -> list[Path]:
    work = tmp_path_factory.mktemp("ocr")
    out = []
    for page, device, dpi in CASES:
        pdf = write_pdf(work / f"{page}.pdf", *PAGES[page])
        png = work / f"{page}-{device}-{dpi}.png"
        pyjpdfium.rasterize_page(pdf, 0, png, device=device, raster_dpi=dpi)
        out.append(png)
    return out


@pytest.fixture(scope="module")
def reference(images) -> dict[str, dict]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYJPDFIUM")}
    done = subprocess.run([REFERENCE, "-I", str(RUNNER), PROFILE, *map(str, images)],
                          capture_output=True, text=True, env=env, check=False, timeout=900)
    assert done.returncode == 0, done.stderr[-4000:]
    results = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    return {r["image"]: r for r in results}


@pytest.fixture(scope="module")
def engine():
    with pyjpdfium.OcrEngine(PROFILE) as e:
        yield e


@pytest.mark.parametrize("case", range(len(CASES)), ids=["-".join(map(str, c)) for c in CASES])
def test_matches_reference(case, images, reference, engine):
    image = images[case]
    want = reference[str(image)]
    got = engine.recognize(image)
    assert [line.text for line in got.lines] == want["texts"]
    assert [[[int(x), int(y)] for x, y in line.polygon] for line in got.lines] == want["polys"]
    for line, score in zip(got.lines, want["scores"]):
        assert line.confidence == pytest.approx(score, abs=1e-6), line.text
    assert got.lines, "every fixture has text"
