import math

import pytest

import pyjpdfium
from pyjpdfium import errors

pytestmark = pytest.mark.native


@pytest.fixture
def gray_page(pdf_path):
    with pyjpdfium.open_document(pdf_path) as doc, doc.page(0) as page:
        bitmap = page.render(dpi=72, pixel_format="gray")
    yield bitmap
    bitmap.close()


def test_identity_quad_in_any_order_is_exact(gray_page):
    source = gray_page.tobytes()
    corners = [(612, 792), (0, 0), (0, 792), (612, 0)]
    for interpolation in ("nearest", "bilinear", "bicubic"):
        out, result = gray_page.rectify(corners, interpolation=interpolation)
        with out:
            assert (out.width, out.height) == (612, 792)
            assert out.tobytes() == source
    assert result.quad == ((0, 0), (612, 0), (612, 792), (0, 792))


def test_crop_maps_back_to_source(gray_page):
    quad = [72, 92, 172, 92, 172, 192, 72, 192]
    out, result = gray_page.rectify(quad, interpolation="nearest")
    with out:
        assert (out.width, out.height) == (100, 100)
        assert out.view()[50, 50] == 0
    sx, sy = result.map_to_source(100, 100)
    assert math.isclose(sx, 172) and math.isclose(sy, 192)


def test_explicit_size_and_budget(gray_page):
    quad = [72, 92, 172, 92, 172, 192, 72, 192]
    out, _ = gray_page.rectify(quad, size=(320, 48), border="replicate", interpolation="bicubic")
    with out:
        assert (out.width, out.height) == (320, 48)
    with pytest.raises(errors.LimitExceededError):
        gray_page.rectify(quad, size=(4000, 4000), max_pixels=1_000_000)


@pytest.mark.parametrize(
    "quad",
    [[0, 0, 10, 0, 20, 0, 30, 0], [0, 0, 10, 0, 2, 2, 0, 10], [0, 0, 10, 0, 10, float("nan"), 0, 10]],
    ids=["collinear", "concave", "nan"],
)
def test_degenerate_quads_are_rejected(gray_page, quad):
    with pytest.raises(errors.InvalidArgumentError):
        gray_page.rectify(quad)
