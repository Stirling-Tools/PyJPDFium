import struct

import pytest

import pyjpdfium
from pyjpdfium import errors

pytestmark = pytest.mark.native

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunks(data):
    assert data[:8] == PNG_SIGNATURE
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        yield kind, data[pos + 8 : pos + 8 + length]
        pos += 12 + length


def staging_leftovers(directory):
    return [p.name for p in directory.iterdir() if ".jpdf-" in p.name]


def test_render_to_file_writes_png_with_dpi(pdf_path, tmp_path):
    out = tmp_path / "page.png"
    with pyjpdfium.open_document(pdf_path) as doc, doc.page(0) as page:
        assert page.render(out, dpi=(300, 150), pixel_format="gray") is None
    chunks = dict(png_chunks(out.read_bytes()))
    width, height, depth, color = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (width, height, depth, color) == (2550, 1650, 8, 0)
    ppm_x, ppm_y, unit = struct.unpack(">IIB", chunks[b"pHYs"])
    assert (round(ppm_x * 0.0254), round(ppm_y * 0.0254), unit) == (300, 150, 1)
    assert staging_leftovers(tmp_path) == []


def test_failed_write_leaves_destination_untouched(pdf_path, tmp_path):
    out = tmp_path / "page.png"
    out.write_bytes(b"previous content")
    with pyjpdfium.open_document(pdf_path) as doc, doc.page(1) as page:
        with pytest.raises(errors.LimitExceededError):
            page.render(out, dpi=100, max_bytes=64)
        bitmap = page.render(dpi=50)
    with pytest.raises(errors.LimitExceededError):
        bitmap.save(out, max_bytes=10)
    assert out.read_bytes() == b"previous content"
    assert staging_leftovers(tmp_path) == []
    with pytest.raises(errors.PdfIOError):
        bitmap.save(tmp_path / "missing-dir" / "page.png")
    bitmap.save(out, durable=True)
    assert out.read_bytes()[:8] == PNG_SIGNATURE
    bitmap.close()
