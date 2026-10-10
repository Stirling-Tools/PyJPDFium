import pytest

import pyjpdfium
from pyjpdfium import PixelFormat, errors

pytestmark = pytest.mark.native


def pixel(bitmap, x, y):
    view = bitmap.view()
    if view.ndim == 2:
        return view[y, x]
    return tuple(view[y, x, c] for c in range(view.shape[2]))


def test_render_size_format_and_content(pdf_path):
    with pyjpdfium.open_document(pdf_path) as doc, doc.page(0) as page:
        with page.render(dpi=72) as bitmap:
            assert (bitmap.width, bitmap.height) == (612, 792)
            assert bitmap.pixel_format is PixelFormat.RGB
            assert bitmap.info.stride == 612 * 3
            assert bitmap.info.dpi == (72.0, 72.0)
            # Square spans x 72-172pt, y 600-700pt; image rows run top down.
            assert pixel(bitmap, 122, 792 - 650) == (0, 0, 0)
            assert pixel(bitmap, 400, 792 - 650) == (255, 255, 255)
        with page.render(dpi=(36, 18), pixel_format="gray") as gray:
            assert (gray.width, gray.height) == (306, 198)
            assert gray.view().shape == (198, 306)
        with page.render(size=(100, 50), pixel_format=PixelFormat.RGBA, transparent=True) as rgba:
            assert (rgba.width, rgba.height) == (100, 50)
            assert pixel(rgba, 99, 49)[3] == 0


def test_bitmap_outlives_page_and_document(pdf_path):
    doc = pyjpdfium.open_document(pdf_path)
    page = doc.page(3)
    bitmap = page.render(dpi=20, pixel_format="gray")
    data = bitmap.tobytes()
    page.close()
    doc.close()
    assert bitmap.tobytes() == data
    bitmap.close()


def test_view_retains_pixels_after_bitmap_close(pdf_path):
    with pyjpdfium.open_document(pdf_path) as doc, doc.page(0) as page:
        bitmap = page.render(dpi=20)
    expected = bitmap.tobytes()
    view = bitmap.view()
    bitmap.close()
    assert view.tobytes() == expected
    assert pyjpdfium.runtime_info().live_views >= 1
    with pytest.raises(errors.StaleHandleError):
        bitmap.view()
    with pytest.raises(TypeError):
        view[0, 0, 0] = 1
    del view
    assert pyjpdfium.runtime_info().live_views == 0


def test_invalid_render_options(pdf_path):
    with pyjpdfium.open_document(pdf_path) as doc, doc.page(0) as page:
        with pytest.raises(errors.InvalidArgumentError):
            page.render(dpi=0)
        with pytest.raises(errors.InvalidArgumentError):
            page.render(pixel_format="rgb", transparent=True)
        with pytest.raises(errors.LimitExceededError):
            page.render(dpi=72, max_pixels=100)
        with pytest.raises(KeyError):
            page.render(pixel_format="cmyk")


def test_capabilities():
    assert pyjpdfium.capability("pdf.render") is pyjpdfium.Capability.IMPLEMENTED
    assert pyjpdfium.capability("ocr.recognize") is pyjpdfium.Capability.ABSENT


def test_runtime_identity():
    info = pyjpdfium.runtime_info()
    assert info.state is pyjpdfium.RuntimeState.RUNNING
    assert info.api_version[0] == 1
    assert info.renderer is not None
    assert info.build_id.startswith("jpdfium ")
