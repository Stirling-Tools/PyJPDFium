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


def one_word(text, box=(0, 0, 100, 50)):
    return [TextLine(box, (TextWord(text, box),))]


@pytest.mark.parametrize(
    ("lines", "error"),
    [
        (one_word("שלום"), errors.UnsupportedError),  # right-to-left is not laid out yet
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
