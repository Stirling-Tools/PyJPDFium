"""End-to-end OCRmyPDF runs with the pyjpdfium.ocrmypdf plugin.

Opt-in: set PYJPDFIUM_OCRMYPDF_PYTHON to a Python with OCRmyPDF 17.13 and pyjpdfium installed
(tests/ocrmypdf/requirements.txt, hash-pinned), and PYJPDFIUM_OCR_PROFILE to a fetched profile.
OCRmyPDF runs as its real command line in a child process; results are read back here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import zlib
from pathlib import Path

import pytest

import pyjpdfium

PYTHON = os.environ.get("PYJPDFIUM_OCRMYPDF_PYTHON")
PROFILE = os.environ.get("PYJPDFIUM_OCR_PROFILE")
HERE = Path(__file__).parent
pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(not (PYTHON and PROFILE),
                       reason="PYJPDFIUM_OCRMYPDF_PYTHON and PYJPDFIUM_OCR_PROFILE are not set"),
]

LINES = ["The quick brown fox jumps", "over the lazy dog", "Invoice number 4821"]
FONT = "/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>"


def pdf_bytes(pages: list[tuple[str, str, dict[str, bytes]]]) -> bytes:
    """Pages of (page dictionary extras, content, image XObjects by name)."""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for extra, content, images in pages:
        page_number = len(objects) + 1
        objects.append(b"")  # the page, filled in below
        content_number = len(objects) + 1
        data = content.encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
        xobjects = []
        for name, image in images.items():
            xobjects.append(f"/{name} {len(objects) + 1} 0 R")
            objects.append(image)
        resources = f"/Resources << /XObject << {' '.join(xobjects)} >> >>" if images else ""
        objects[page_number - 1] = (f"<< /Type /Page /Parent 2 0 R {extra} {resources} "
                                    f"/Contents {content_number} 0 R >>").encode("latin-1")
        kids.append(f"{page_number} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out, offsets = bytearray(b"%PDF-1.7\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1,
                                                                               xref)
    return bytes(out)


def text_page() -> tuple[str, str, dict[str, bytes]]:
    content = "".join(f"BT /F1 22 Tf 72 {700 - 60 * i} Td ({line}) Tj ET "
                      for i, line in enumerate(LINES))
    return f"/MediaBox [0 0 612 792] {FONT}", content, {}


def scan(tmp_path: Path, name: str = "scan") -> tuple[bytes, int, int]:
    """The text page rasterized at 300 dpi: an 8-bit gray image XObject and its size."""
    source = tmp_path / f"{name}-source.pdf"
    source.write_bytes(pdf_bytes([text_page()]))
    png = tmp_path / f"{name}.png"
    pyjpdfium.rasterize_page(source, 0, png, device="pnggray", raster_dpi=300)
    with pyjpdfium.load_image(png) as bitmap:
        gray = bitmap.tobytes()[0::3] if bitmap.pixel_format.name == "RGB8" else bitmap.tobytes()
        width, height = bitmap.width, bitmap.height
    data = zlib.compress(gray)
    image = (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
             b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n"
             % (width, height, len(data)) + data + b"\nendstream")
    return image, width, height


def scanned_page(tmp_path: Path, rotate: bool = False) -> tuple[str, str, dict[str, bytes]]:
    image, _, _ = scan(tmp_path, "rotated" if rotate else "scan")
    if not rotate:
        return "/MediaBox [0 0 612 792]", "q 612 0 0 792 0 0 cm /Im0 Do Q", {"Im0": image}
    # Stored a quarter turn anticlockwise, so /Rotate 90 displays it upright.
    return "/MediaBox [0 0 792 612] /Rotate 90", "q 0 612 -792 0 792 0 cm /Im0 Do Q", {"Im0": image}


def ocrmypdf(*args: str, plugins=("pyjpdfium.ocrmypdf",)) -> subprocess.CompletedProcess:
    command = [PYTHON, "-m", "ocrmypdf"]
    for plugin in plugins:
        command += ["--plugin", plugin]
    env = {**os.environ, "PYJPDFIUM_OCR_PROFILE": PROFILE}
    return subprocess.run([*command, *args], capture_output=True, text=True, env=env,
                          check=False, timeout=600)


def page_texts(path: Path) -> list[str]:
    with pyjpdfium.open_document(path) as document:
        texts = []
        for index in range(document.page_count):
            with document.page(index) as page:
                texts.append(" ".join(page.text().split()))
        return texts


def render(path: Path, index: int = 0) -> bytes:
    with pyjpdfium.open_document(path) as document, document.page(index) as page:
        with page.render(dpi=50, pixel_format="gray") as bitmap:
            return bitmap.tobytes()


def ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stderr[-3000:]


EXPECTED = " ".join(LINES)


def test_scanned_page_gains_text_and_looks_the_same(tmp_path):
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_bytes([scanned_page(tmp_path)]))
    out, sidecar = tmp_path / "out.pdf", tmp_path / "out.txt"
    ok(ocrmypdf("--output-type", "pdf", "--sidecar", str(sidecar), str(source), str(out)))
    assert page_texts(source) == [""]
    assert page_texts(out) == [EXPECTED]
    assert render(out) == render(source), "OCR must not change what the page shows"
    assert sidecar.read_text(encoding="utf-8").split("\n")[:3] == LINES


def test_engine_value_is_registered_on_the_command_line(tmp_path):
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_bytes([scanned_page(tmp_path)]))
    out = tmp_path / "out.pdf"
    ok(ocrmypdf("--ocr-engine", "pyjpdfium", "--output-type", "pdf", str(source), str(out)))
    assert page_texts(out) == [EXPECTED]
    unloaded = ocrmypdf("--ocr-engine", "pyjpdfium", str(source), str(out), plugins=())
    assert unloaded.returncode == 2, "without the plugin the value must stay unknown"


def test_rotated_page_reads_upright(tmp_path):
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_bytes([scanned_page(tmp_path, rotate=True)]))
    out = tmp_path / "out.pdf"
    ok(ocrmypdf("--output-type", "pdf", str(source), str(out)))
    assert page_texts(out) == [EXPECTED]
    assert render(out) == render(source)


def test_modes_with_existing_text(tmp_path):
    source = tmp_path / "mixed.pdf"
    source.write_bytes(pdf_bytes([text_page(), scanned_page(tmp_path)]))
    out = tmp_path / "out.pdf"
    refused = ocrmypdf("--output-type", "pdf", str(source), str(out))
    assert refused.returncode == 6, "default mode refuses pages that already have text"

    ok(ocrmypdf("--output-type", "pdf", "--skip-text", str(source), str(out)))
    assert page_texts(out) == [EXPECTED, EXPECTED]
    assert render(out, 0) == render(source, 0), "--skip-text leaves the text page alone"

    forced = tmp_path / "forced.pdf"
    ok(ocrmypdf("--output-type", "pdf", "--force-ocr", str(source), str(forced)))
    assert page_texts(forced) == [EXPECTED, EXPECTED]


def test_redo_replaces_earlier_ocr_without_doubling(tmp_path):
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_bytes([scanned_page(tmp_path)]))
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    ok(ocrmypdf("--output-type", "pdf", str(source), str(first)))
    ok(ocrmypdf("--output-type", "pdf", "--redo-ocr", str(first), str(second)))
    assert page_texts(second) == [EXPECTED]
    assert render(second) == render(source)


def test_engine_reads_the_image_ocrmypdf_supplies(tmp_path):
    # mask_plugin.py blanks the first line in each OCR image only, so it must not be found.
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_bytes([scanned_page(tmp_path)]))
    out = tmp_path / "out.pdf"
    ok(ocrmypdf("--output-type", "pdf", str(source), str(out),
                plugins=("pyjpdfium.ocrmypdf", str(HERE / "mask_plugin.py"))))
    assert page_texts(out) == [" ".join(LINES[1:])]
    assert render(out) == render(source), "the visible page keeps every line"


@pytest.mark.parametrize("workers", [(), ("--no-use-threads",)], ids=["threads", "processes"])
def test_pages_in_parallel_workers(tmp_path, workers):
    # Forked workers each open their own engine; threads share one.
    source = tmp_path / "in.pdf"
    page = scanned_page(tmp_path)
    source.write_bytes(pdf_bytes([page, page, page]))
    out = tmp_path / "out.pdf"
    ok(ocrmypdf("--output-type", "pdf", "--jobs", "2", *workers, str(source), str(out)))
    assert page_texts(out) == [EXPECTED] * 3


def test_fpdf2_reference_renderer_reads_the_same_words(tmp_path):
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_bytes([scanned_page(tmp_path)]))
    out = tmp_path / "out.pdf"
    ok(ocrmypdf("--output-type", "pdf", "--pdf-renderer", "fpdf2", str(source), str(out)))
    assert page_texts(out)[0].split() == EXPECTED.split()


@pytest.mark.parametrize(
    ("args", "code", "message"),
    [
        ((), 1, "PDF/A"),  # the default output type is best-effort PDF/A
        (("--output-type", "pdfa"), 1, "PDF/A"),
        (("--output-type", "pdf", "--deskew"), 1, "--deskew"),
        (("--output-type", "pdf", "--rotate-pages"), 1, "--rotate-pages"),
        # Without unpaper installed, OCRmyPDF refuses --clean itself, before this plugin.
        (("--output-type", "pdf", "--clean"), (1, 3), "--clean"),
        (("--output-type", "pdf", "--ocr-engine", "tesseract"), 1, "tesseract"),
        (("--output-type", "pdf", "-l", "deu"), 3, "deu"),
        (("--output-type", "pdf", "--tesseract-timeout", "5"), 2, "--tesseract-timeout"),
        (("--output-type", "pdf", "--pyjpdfium-threads", "-1"), 1, "threads"),
    ],
)
def test_unsupported_modes_are_refused(tmp_path, args, code, message):
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_bytes([text_page()]))
    out = tmp_path / "out.pdf"
    result = ocrmypdf(*args, str(source), str(out))
    codes = code if isinstance(code, tuple) else (code,)
    assert result.returncode in codes, result.stderr[-2000:]
    assert message in result.stderr
    assert not out.exists()


def test_a_tampered_profile_is_refused_before_any_page(tmp_path):
    profile = tmp_path / "profile"
    shutil.copytree(PROFILE, profile)
    with (profile / "dictionary.txt").open("ab") as handle:
        handle.write(b"x\n")
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_bytes([scanned_page(tmp_path)]))
    out = tmp_path / "out.pdf"
    result = ocrmypdf("--output-type", "pdf", "--pyjpdfium-profile", str(profile), str(source),
                      str(out))
    assert result.returncode == 1 and "pinned digest" in result.stderr
    assert not out.exists()


def test_runs_without_tesseract_or_ghostscript(tmp_path):
    present = [tool for tool in ("tesseract", "gs") if shutil.which(tool)]
    if present:
        pytest.skip(f"installed here: {present}")
    source = tmp_path / "in.pdf"
    source.write_bytes(pdf_bytes([scanned_page(tmp_path)]))
    out = tmp_path / "out.pdf"
    ok(ocrmypdf("--output-type", "pdf", "--jobs", "2", str(source), str(out)))
    assert page_texts(out) == [EXPECTED]
