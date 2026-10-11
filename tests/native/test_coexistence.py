import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.native

# pypdfium2 first, as OCRmyPDF imports it, then pyjpdfium in the same process.
PROBE = r"""
import sys
import pypdfium2
import pyjpdfium
from pyjpdfium.errors import NativeLoadError

pdf = pypdfium2.PdfDocument(sys.argv[1])
theirs = pdf[0].render(scale=1).to_pil().size
try:
    with pyjpdfium.open_document(sys.argv[1]) as document, document.page(0) as page:
        ours = page.size
except NativeLoadError as exc:
    print("refused:", exc)
    raise SystemExit(0)
maps = open("/proc/self/maps").read()
pdfiums = sorted({line.split()[-1] for line in maps.splitlines()
                  if "pdfium" in line.split()[-1] and line.split()[-1].startswith("/")})
print("shared:", theirs, round(ours.width), round(ours.height), pdfiums)
"""


def test_pyjpdfium_and_pypdfium2_share_a_process(tmp_path):
    if importlib.util.find_spec("pypdfium2") is None:  # never imported here: it loads PDFium
        pytest.skip("pypdfium2 is not installed")
    if not sys.platform.startswith("linux"):
        pytest.skip("soname staging is Linux-only")
    directory = Path(os.environ.get("PYJPDFIUM_NATIVE_DIR", ""))
    pdf = tmp_path / "page.pdf"
    pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
                    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] >>\n"
                    b"endobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n")
    result = subprocess.run([sys.executable, "-c", PROBE, str(pdf)], capture_output=True,
                            text=True, check=False, timeout=120)
    assert result.returncode == 0, result.stderr
    if (directory / "libpdfium.so").exists():
        # Unstaged natives would bind to pypdfium2's PDFium; the loader says so instead.
        assert "refused:" in result.stdout and "stage_natives.py" in result.stdout
    else:
        assert "shared: (200, 100) 200 100" in result.stdout
        assert "libjpdfium_pdfium.so" in result.stdout and "pypdfium2" in result.stdout
