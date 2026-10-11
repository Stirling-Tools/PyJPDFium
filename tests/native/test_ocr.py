import importlib.util
import os
import shutil
import subprocess
import sys
import threading

import pytest

import pyjpdfium
from pyjpdfium import errors

PROFILE = os.environ.get("PYJPDFIUM_OCR_PROFILE")
pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(not PROFILE, reason="PYJPDFIUM_OCR_PROFILE is not set"),
    pytest.mark.skipif(importlib.util.find_spec("pyjpdfium._ocr_native") is None,
                       reason="pyjpdfium was built without the OCR module"),
]

LINES = ["The quick brown fox jumps over the lazy dog.", "Invoice 2026-10-11 total 1,234.56 EUR"]


def page_pdf(tmp_path):
    content = (f"BT /F1 18 Tf 72 700 Td ({LINES[0]}) Tj 0 -40 Td /F1 12 Tf ({LINES[1]}) Tj ET")
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 << "
        "/Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> /Contents 4 0 R >>",
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
    path = tmp_path / "page.pdf"
    path.write_bytes(bytes(out))
    return path


@pytest.fixture(scope="module")
def engine():
    with pyjpdfium.OcrEngine(PROFILE) as e:
        yield e


def test_engine_identity(engine):
    assert engine.profile == "pp-ocrv6-small"
    assert engine.runtime_version == "1.30.0"


def test_png_file_is_read_like_opencv(tmp_path, engine):
    png = tmp_path / "page.png"
    pyjpdfium.rasterize_page(page_pdf(tmp_path), 0, png, device="pnggray", raster_dpi=300)
    result = engine.recognize(png)
    assert [line.text for line in result.lines] == LINES
    assert result.image_size == (2550, 3300)
    assert result.dpi[0] == pytest.approx(300, abs=0.01)
    assert result.word_geometry == "absent"
    assert all(0.9 < line.confidence <= 1 for line in result.lines)


def test_bitmap_input_and_independent_lifetimes(tmp_path, engine):
    with pyjpdfium.open_document(page_pdf(tmp_path)) as document, document.page(0) as page:
        bitmap = page.render(dpi=300, pixel_format="rgb")
    result = engine.recognize(bitmap)
    bitmap.close()  # the result owns copies; nothing depends on the bitmap any more
    assert result.text.splitlines() == LINES


def test_ocr_feeds_the_text_layer(tmp_path, engine):
    png = tmp_path / "page.png"
    pyjpdfium.rasterize_page(page_pdf(tmp_path), 0, png, device="pnggray", raster_dpi=300)
    result = engine.recognize(png)
    layer = tmp_path / "layer.pdf"
    pyjpdfium.write_text_layer(layer, result.text_lines(), image_size=result.image_size, dpi=300)
    with pyjpdfium.open_document(layer) as document, document.page(0) as page:
        assert " ".join(page.text().split()) == " ".join(LINES)


def test_concurrent_recognitions_agree(tmp_path, engine):
    png = tmp_path / "page.png"
    pyjpdfium.rasterize_page(page_pdf(tmp_path), 0, png, device="pnggray", raster_dpi=150)
    texts, failures = [], []

    def worker():
        try:
            texts.append(engine.recognize(png).text)
        except Exception as exc:  # noqa: BLE001 - reported below
            failures.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not failures and len(set(texts)) == 1


def test_tampered_profile_is_refused(tmp_path):
    copy = tmp_path / "profile"
    shutil.copytree(PROFILE, copy)
    with (copy / "dictionary.txt").open("a", encoding="utf-8") as f:
        f.write("x\n")
    with pytest.raises(errors.PdfFormatError, match="digest"):
        pyjpdfium.OcrEngine(copy)


def test_closed_engine_is_stale(tmp_path):
    engine = pyjpdfium.OcrEngine(PROFILE)
    engine.close()
    with pytest.raises(errors.StaleHandleError):
        engine.recognize(tmp_path / "unused.png")


PROBE = """
import pyjpdfium
with pyjpdfium.open_document(r"{pdf}") as d:
    pass
maps = open("/proc/self/maps").read()
assert "onnxruntime" not in maps and "jpdfium_ocr" not in maps, "OCR loaded too early"
engine = pyjpdfium.OcrEngine(r"{profile}")
maps = open("/proc/self/maps").read()
assert "onnxruntime" in maps and "jpdfium_ocr" in maps
print("lazy-ok")
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc/self/maps")
def test_ocr_module_loads_only_when_used(tmp_path):
    probe = PROBE.format(pdf=page_pdf(tmp_path), profile=PROFILE)
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr
    assert "lazy-ok" in done.stdout
