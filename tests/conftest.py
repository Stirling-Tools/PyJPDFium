from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PAGES = 4


def fixture_pdf(pages: int = PAGES) -> bytes:
    """Page i is 612x792pt with a black 100pt square at x = 72 + 100 * i, y = 600."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(pages))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>")
    for i in range(pages):
        content = f"0 0 0 rg {72 + i * 100} 600 100 100 re f"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + i * 2} 0 R >>"
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


@pytest.fixture
def pdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.pdf"
    path.write_bytes(fixture_pdf())
    return path


def pytest_collection_modifyitems(config, items):
    if importlib.util.find_spec("pyjpdfium._native") is not None:
        return
    skip = pytest.mark.skip(reason="pyjpdfium._native is not built")
    for item in items:
        if "native" in item.keywords:
            item.add_marker(skip)
