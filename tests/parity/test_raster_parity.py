"""Raster parity with OCRmyPDF's pypdfium rasterizer, the reference for jpdf_rasterize_page_file.

Opt-in: set PYJPDFIUM_PARITY_SRC to the directory printed by fetch_reference.py and install
requirements.txt. The reference runs in a separate process so its PDFium never shares ours.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import pyjpdfium

SOURCE = os.environ.get("PYJPDFIUM_PARITY_SRC")
RUNNER = Path(__file__).with_name("reference_runner.py")
Image = pytest.importorskip("PIL.Image") if SOURCE else None
pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(not SOURCE, reason="PYJPDFIUM_PARITY_SRC is not set"),
]

PAGES = {
    "square": ("/MediaBox [0 0 612 792]", "0 0 0 rg 72 600 100 100 re f 0.4 g 300 200 150 80 re f"),
    "text": (
        "/MediaBox [0 0 612 792] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
        "/BaseFont /Helvetica >> >> >>",
        "BT /F1 18 Tf 72 700 Td (The quick brown fox jumps over the lazy dog.) Tj "
        "0 -40 Td /F1 9 Tf (Small print 0123456789 still has to survive OCR.) Tj ET",
    ),
    "ramp": (
        "/MediaBox [0 0 512 792]",
        "".join(f"{g / 255:.4f} g {g * 2} 0 2 792 re f " for g in range(256)),
    ),
}


def write_pdf(path: Path, page_extra: str, content: str) -> Path:
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R {page_extra} /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
    ]
    out, offsets = bytearray(b"%PDF-1.7\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += b"xref\n0 5\n0000000000 65535 f \n"
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


def reference(pdf: Path, out: Path, device: str, dpi, rotation=0, use_cropbox=False) -> dict:
    request = {"input": str(pdf), "output": str(out), "device": device, "raster_dpi": list(dpi),
               "pageno": 1, "rotation": rotation, "use_cropbox": use_cropbox}
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYJPDFIUM")}
    done = subprocess.run([sys.executable, "-I", str(RUNNER), SOURCE, json.dumps(request)],
                          capture_output=True, text=True, env=env, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def difference(a: Path, b: Path) -> tuple[float, float]:
    """Mean absolute difference (0-255) and the fraction of differing samples."""
    from PIL import ImageChops

    with Image.open(a) as x, Image.open(b) as y:
        x, y = x.convert("L" if x.mode in ("1", "L") else "RGB"), y.convert(
            "L" if y.mode in ("1", "L") else "RGB")
        histogram = ImageChops.difference(x, y).histogram()
    total = sum(histogram)
    bands = len(histogram) // 256
    per_value = [sum(histogram[v + 256 * b] for b in range(bands)) for v in range(256)]
    return sum(v * n for v, n in enumerate(per_value)) / total, 1 - per_value[0] / total


@pytest.mark.parametrize("page", sorted(PAGES))
@pytest.mark.parametrize("device", ["pnggray", "png16m", "pngmonod"])
@pytest.mark.parametrize("dpi", [72, 150, 300])
@pytest.mark.parametrize("rotation", [0, 90])
def test_matches_reference(tmp_path, page, device, dpi, rotation):
    pdf = write_pdf(tmp_path / "in.pdf", *PAGES[page])
    ref = reference(pdf, tmp_path / "ref.png", device, (dpi, dpi), rotation)
    ours = pyjpdfium.rasterize_page(pdf, 0, tmp_path / "ours.png", device=device,
                                    raster_dpi=dpi, rotation=rotation)
    with Image.open(tmp_path / "ours.png") as image:
        assert list(image.size) == ref["size"]
        assert image.mode == ref["mode"]
        assert [round(v, 3) for v in image.info["dpi"]] == [round(v, 3) for v in ref["dpi"]]
    assert (ours.width, ours.height) == tuple(ref["size"])
    mean, changed = difference(tmp_path / "ours.png", tmp_path / "ref.png")
    # Measured against pypdfium2 5.14.0: identical except RGB text (0.27% of samples, mean 0.003),
    # where the two PDFium builds anti-alias glyph edges slightly differently.
    assert mean < 0.05 and changed < 0.01, f"mean {mean:.4f}, changed {changed:.5f}"


def test_deviation_partial_cropbox(tmp_path):
    # Reference: expected size comes from the CropBox, one axis is within 2 px, so the MediaBox
    # render is cropped from its top-left corner. Ours renders the whole MediaBox.
    pdf = write_pdf(tmp_path / "in.pdf", "/MediaBox [0 0 612 792] /CropBox [0 100 612 500]",
                    "0 g 0 0 612 792 re f")
    ref = reference(pdf, tmp_path / "ref.png", "pnggray", (72, 72))
    ours = pyjpdfium.rasterize_page(pdf, 0, tmp_path / "o.png", device="pnggray", raster_dpi=72)
    assert ref["size"] == [612, 400]
    assert (ours.width, ours.height) == (612, 792)


def test_deviation_non_square_dpi(tmp_path):
    # Reference renders both axes at the harmonic mean; ours honours each axis like Ghostscript.
    pdf = write_pdf(tmp_path / "in.pdf", *PAGES["square"])
    ref = reference(pdf, tmp_path / "ref.png", "pnggray", (300, 150))
    ours = pyjpdfium.rasterize_page(pdf, 0, tmp_path / "o.png", device="pnggray",
                                    raster_dpi=(300, 150))
    assert ref["size"] == [1700, 2200]
    assert (ours.width, ours.height) == (2550, 1650)


def test_deviation_rotation_on_rotated_page(tmp_path):
    # Reference overwrites /Rotate; ours adds the correction to it, as Ghostscript does.
    pdf = write_pdf(tmp_path / "in.pdf", "/MediaBox [0 0 612 792] /Rotate 90", "0 g 72 600 100 100 re f")
    ref = reference(pdf, tmp_path / "ref.png", "pnggray", (72, 72), rotation=90)
    ours = pyjpdfium.rasterize_page(pdf, 0, tmp_path / "o.png", device="pnggray", raster_dpi=72,
                                    rotation=90)
    assert ref["size"] == [792, 612]
    assert (ours.width, ours.height) == (612, 792)
