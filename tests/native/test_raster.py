import importlib.util

import pytest
from pngread import read_png

import pyjpdfium
from pyjpdfium import errors

pytestmark = pytest.mark.native


def one_page(tmp_path, name, page_extra, content="0 0 0 rg 72 600 100 100 re f"):
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
    path = tmp_path / name
    path.write_bytes(bytes(out))
    return path


@pytest.fixture
def letter(tmp_path):
    return one_page(tmp_path, "letter.pdf", "/MediaBox [0 0 612 792]")


@pytest.mark.parametrize(
    ("device", "depth", "color"),
    [("png16m", 8, 2), ("pnggray", 8, 0), ("pngmonod", 1, 0), ("pngmono", 1, 0),
     ("png256", 8, 2), ("pngalpha", 8, 2)],
)
def test_devices_produce_the_reference_png_modes(letter, tmp_path, device, depth, color):
    out = tmp_path / f"{device}.png"
    result = pyjpdfium.rasterize_page(letter, 0, out, device=device, raster_dpi=72)
    png = read_png(out)
    assert (png.width, png.height, png.bit_depth, png.color_type) == (612, 792, depth, color)
    assert result.bits_per_pixel == (1 if depth == 1 else 8 * png.channels)
    # The square spans x 72-172pt and y 600-700pt; rows run top down.
    assert png.pixel(122, 142)[0] == 0
    assert png.pixel(400, 142)[0] in (1, 255)


def test_dpi_metadata_follows_pillow(letter, tmp_path):
    out = tmp_path / "dpi.png"
    pyjpdfium.rasterize_page(letter, 0, out, raster_dpi=300, output_dpi=(200, 100))
    png = read_png(out)
    assert (png.width, png.height) == (2550, 3300)
    assert png.ppm == (int(200 / 0.0254 + 0.5), int(100 / 0.0254 + 0.5))


def test_quarter_turn_follows_ghostscript(letter, tmp_path):
    out = tmp_path / "rot.png"
    result = pyjpdfium.rasterize_page(letter, 0, out, device="pnggray", raster_dpi=(300, 150),
                                      rotation=90)
    assert (result.width, result.height) == (1650, 2550)
    assert result.dpi == (150.0, 300.0)
    png = read_png(out)
    # A counterclockwise turn moves the square from the top-left to the bottom-left.
    assert png.pixel(int(142 * 150 / 72), int((612 - 122) * 300 / 72))[0] == 0
    assert png.pixel(int(142 * 150 / 72), int(122 * 300 / 72))[0] == 255


def test_cropbox_policy(tmp_path):
    pdf = one_page(tmp_path, "box.pdf", "/MediaBox [0 0 612 792] /CropBox [100 100 400 500]")
    media = pyjpdfium.rasterize_page(pdf, 0, tmp_path / "m.png", device="pnggray", raster_dpi=72)
    crop = pyjpdfium.rasterize_page(pdf, 0, tmp_path / "c.png", device="pnggray", raster_dpi=72,
                                    use_cropbox=True)
    assert (media.width, media.height) == (612, 792)
    assert (crop.width, crop.height) == (300, 400)


def test_python_rounding_semantics(tmp_path):
    # 5pt at 36 dpi is 2.5 px; Python's round() gives 2.
    pdf = one_page(tmp_path, "tiny.pdf", "/MediaBox [0 0 5 5]", "0 g 0 0 5 5 re f")
    result = pyjpdfium.rasterize_page(pdf, 0, tmp_path / "t.png", device="pnggray", raster_dpi=36)
    assert (result.width, result.height) == (round(2.5), round(2.5)) == (2, 2)


def test_unsupported_requests_are_refused(letter, tmp_path):
    out = tmp_path / "x.png"
    for device in ("jpeggray", "tiff", "nonsense"):
        with pytest.raises(errors.UnsupportedError):
            pyjpdfium.rasterize_page(letter, 0, out, device=device)
    with pytest.raises(errors.UnsupportedError):
        pyjpdfium.rasterize_page(letter, 0, out, filter_vector=True)
    with pytest.raises(errors.InvalidArgumentError):
        pyjpdfium.rasterize_page(letter, 0, out, rotation=45)
    with pytest.raises(errors.PageNotFoundError):
        pyjpdfium.rasterize_page(letter, 1, out)
    with pytest.raises(errors.LimitExceededError):
        pyjpdfium.rasterize_page(letter, 0, out, max_pixels=100)
    assert not out.exists()


@pytest.mark.skipif(importlib.util.find_spec("PIL") is None, reason="Pillow is not installed")
def test_mono_matches_pillow_floyd_steinberg(tmp_path):
    from PIL import Image

    # A smooth gradient exercises error diffusion across every gray level.
    content = "".join(f"{g / 255:.4f} g {g * 2} 0 2 792 re f " for g in range(256))
    pdf = one_page(tmp_path, "ramp.pdf", "/MediaBox [0 0 512 792]", content)
    pyjpdfium.rasterize_page(pdf, 0, tmp_path / "g.png", device="pnggray", raster_dpi=50)
    pyjpdfium.rasterize_page(pdf, 0, tmp_path / "m.png", device="pngmonod", raster_dpi=50)
    gray, mono = read_png(tmp_path / "g.png"), read_png(tmp_path / "m.png")
    expected = Image.frombytes("L", (gray.width, gray.height), b"".join(gray.rows)).convert("1")
    assert mono.gray_bytes() == expected.convert("L").tobytes()
