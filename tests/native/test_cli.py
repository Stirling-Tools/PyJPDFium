import json
import os
import shutil
import subprocess
import sys

import pytest

import pyjpdfium

pytestmark = pytest.mark.native
PROFILE = os.environ.get("PYJPDFIUM_OCR_PROFILE")
TEXT_PAGE = (
    b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 "
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> /Contents 4 0 R >>\nendobj\n"
    b"4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 28 Tf 72 700 Td (Command line) Tj ET\nendstream\n"
    b"endobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


def cli(*args, env=None):
    # A child process, as a user would run it; the package's own entry point.
    return subprocess.run([sys.executable, "-m", "pyjpdfium", *args], capture_output=True,
                          text=True, env={**os.environ, **(env or {})}, check=False, timeout=300)


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "page.pdf"
    path.write_bytes(TEXT_PAGE)
    return path


def test_info_reports_identity_and_capabilities():
    result = cli("info")
    assert result.returncode == 0, result.stderr
    assert f"pyjpdfium {pyjpdfium.__version__}" in result.stdout
    assert "text_layer.bidi" in result.stdout and "implemented" in result.stdout


def test_info_on_a_pdf_lists_its_pages(pdf):
    result = cli("info", str(pdf))
    assert result.returncode == 0, result.stderr
    assert "1 pages" in result.stdout and "612.00 x 792.00 pt" in result.stdout


def test_render_writes_a_png(tmp_path, pdf):
    out = tmp_path / "page.png"
    result = cli("render", str(pdf), str(out), "--dpi", "100", "--device", "pnggray")
    assert result.returncode == 0, result.stderr
    with pyjpdfium.load_image(out) as bitmap:
        assert (bitmap.width, bitmap.height) == (850, 1100)


def test_failures_exit_1_with_a_message(tmp_path):
    result = cli("info", str(tmp_path / "missing.pdf"))
    assert result.returncode == 1
    assert result.stderr.startswith("pyjpdfium info:")


def test_fonts_lists_the_glyphless_font():
    result = cli("fonts")
    assert result.returncode == 0 and result.stdout.startswith("glyphless")


def test_models_refuses_a_tampered_profile(tmp_path):
    if not PROFILE:
        pytest.skip("PYJPDFIUM_OCR_PROFILE is not set")
    assert cli("models", PROFILE).returncode == 0
    copy = tmp_path / "profile"
    shutil.copytree(PROFILE, copy)
    (copy / "det.yml").write_text("tampered\n", encoding="utf-8")
    result = cli("models", str(copy))
    assert result.returncode == 1 and "does not match its pinned digest" in result.stdout


def test_doctor_passes_without_recognizing_anything():
    result = cli("doctor")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 problem(s)" in result.stdout
    assert "capability pdf.render" in result.stdout


def test_doctor_flags_a_broken_profile(tmp_path):
    (tmp_path / "profile.txt").write_text("format 1\n", encoding="utf-8")
    result = cli("doctor", "--profile", str(tmp_path))
    assert result.returncode == 1 and "PROBLEM  ocr profile" in result.stdout


def test_ocr_reads_a_page(tmp_path, pdf):
    if not PROFILE:
        pytest.skip("PYJPDFIUM_OCR_PROFILE is not set")
    layer = tmp_path / "layer.pdf"
    result = cli("ocr", str(pdf), "--layer", str(layer), "--json")
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert [line["text"] for line in found["lines"]] == ["Command line"]
    with pyjpdfium.open_document(layer) as document, document.page(0) as page:
        assert " ".join(page.text().split()) == "Command line"
