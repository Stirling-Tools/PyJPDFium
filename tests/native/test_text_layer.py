import math
import threading

import pytest

import pyjpdfium
from pyjpdfium import TextLine, TextWord, errors

pytestmark = pytest.mark.native

LINES = [
    TextLine((300, 300, 1500, 400), (TextWord("Hello", (300, 300, 800, 400)),
                                     TextWord("world", (900, 300, 1500, 400)))),
    TextLine((300, 500, 1200, 600), (TextWord("second", (300, 500, 900, 600)),
                                     TextWord("line", (950, 500, 1200, 600)))),
]
LETTER = {"image_size": (2550, 3300), "dpi": 300}


def squash(text):
    return " ".join(text.split())


def write(path, lines=LINES, **kwargs):
    pyjpdfium.write_text_layer(path, lines, **{**LETTER, **kwargs})
    return path


def test_round_trip_through_our_own_reader(tmp_path):
    path = write(tmp_path / "layer.pdf")
    with pyjpdfium.open_document(path) as document, document.page(0) as page:
        assert page.size.width == pytest.approx(612) and page.size.height == pytest.approx(792)
        assert squash(page.text()) == "Hello world second line"
        with page.render(dpi=100, pixel_format="gray") as bitmap:
            assert min(bitmap.tobytes()) == 255, "the layer must not draw anything"


def test_empty_layer_is_a_blank_page(tmp_path):
    path = write(tmp_path / "empty.pdf", lines=[])
    with pyjpdfium.open_document(path) as document, document.page(0) as page:
        assert page.text() == ""


def test_writing_never_enters_the_pdfium_domain(tmp_path):
    before = pyjpdfium.runtime_info().domain_acquisitions
    for i in range(20):
        write(tmp_path / f"layer{i}.pdf")
    assert pyjpdfium.runtime_info().domain_acquisitions == before


def test_concurrent_writers_produce_identical_files(tmp_path):
    failures = []

    def worker(n):
        try:
            write(tmp_path / f"t{n}.pdf")
        except Exception as exc:  # noqa: BLE001 - reported below
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not failures
    first = (tmp_path / "t0.pdf").read_bytes()
    assert all((tmp_path / f"t{n}.pdf").read_bytes() == first for n in range(8))


def test_failed_write_keeps_the_destination(tmp_path):
    path = tmp_path / "kept.pdf"
    path.write_bytes(b"previous")
    with pytest.raises(errors.LimitExceededError):
        write(path, max_bytes=64)
    assert path.read_bytes() == b"previous"


def test_right_to_left_and_mixed_lines_read_back_in_logical_order(tmp_path):
    lines = [
        TextLine((900, 300, 1600, 400), (TextWord("שלום", (1300, 300, 1600, 400)),
                                         TextWord("עולם", (900, 300, 1250, 400)))),
        TextLine((900, 500, 1600, 600), (TextWord("مَرْحَبًا", (1100, 500, 1600, 600)),
                                         TextWord("يَا", (900, 500, 1050, 600)))),
        TextLine((300, 700, 950, 800), (TextWord("see", (300, 700, 450, 800)),
                                        TextWord("שלום", (500, 700, 700, 800)),
                                        TextWord("here", (750, 700, 950, 800)))),
    ]
    path = write(tmp_path / "rtl.pdf", lines=lines)
    with pyjpdfium.open_document(path) as document, document.page(0) as page:
        assert squash(page.text()) == "שלום עולם مَرْحَبًا يَا see שלום here"


def rotated(box, degrees, centre):
    a = math.radians(degrees)
    cx, cy = centre
    x0, y0, x1, y1 = box
    return tuple((cx + (x - cx) * math.cos(a) - (y - cy) * math.sin(a),
                  cy + (x - cx) * math.sin(a) + (y - cy) * math.cos(a))
                 for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


@pytest.mark.parametrize("degrees", [15, 90, -90])
def test_rotated_quad_lines_read_back(tmp_path, degrees):
    centre = (1200, 1050)
    words = [("rotated", (1000, 1000, 1350, 1100)), ("text", (1400, 1000, 1600, 1100))]
    line = TextLine((1000, 1000, 1600, 1100),
                    tuple(TextWord(t, b, rotated(b, degrees, centre)) for t, b in words),
                    rotated((1000, 1000, 1600, 1100), degrees, centre))
    path = write(tmp_path / "rotated.pdf", lines=[line])
    with pyjpdfium.open_document(path) as document, document.page(0) as page:
        assert squash(page.text()) == "rotated text"
        with page.render(dpi=100, pixel_format="gray") as bitmap:
            assert min(bitmap.tobytes()) == 255


def one_word(text, box=(0, 0, 100, 50)):
    return [TextLine(box, (TextWord(text, box),))]


MIRRORED = ((0, 50), (100, 50), (100, 0), (0, 0))  # anticlockwise: a mirror image


@pytest.mark.parametrize(
    ("lines", "error"),
    [
        (one_word("a\u202eb"), errors.UnsupportedError),  # explicit overrides are refused
        ([TextLine((0, 0, 100, 50), (TextWord("a", (0, 0, 100, 50)),), MIRRORED)],
         errors.InvalidArgumentError),
        (one_word("a\tb"), errors.InvalidArgumentError),
        (one_word("a\x00b"), errors.InvalidArgumentError),
        (one_word("\ud800"), errors.InvalidArgumentError),
        (one_word(""), errors.InvalidArgumentError),
        (one_word("a", box=(0, 50, 100, 50)), errors.InvalidArgumentError),
        ([TextLine((0, 0, 100, 50), ())], errors.InvalidArgumentError),
    ],
)
def test_rejections(tmp_path, lines, error):
    path = tmp_path / "rejected.pdf"
    with pytest.raises(error):
        write(path, lines=lines)
    assert not path.exists()


def test_page_text_needs_an_open_page(tmp_path):
    path = write(tmp_path / "layer.pdf")
    with pyjpdfium.open_document(path) as document:
        page = document.page(0)
        page.close()
        with pytest.raises(errors.StaleHandleError):
            page.text()
