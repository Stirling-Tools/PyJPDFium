"""Text layers checked by tools independent of JPDFium, and grafted by OCRmyPDF's sandwich code.

Opt-in like the raster parity tests: set PYJPDFIUM_PARITY_SRC and install requirements.txt. Each
tool runs in its own process, so pypdfium2's PDFium never shares ours.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import pyjpdfium
from pyjpdfium import TextLine, TextWord

SOURCE = os.environ.get("PYJPDFIUM_PARITY_SRC")
RUNNER = Path(__file__).with_name("text_layer_runner.py")
pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(not SOURCE, reason="PYJPDFIUM_PARITY_SRC is not set"),
]

DPI = 300.0
SCALE = 72.0 / DPI
IMAGE = (2550, 3300)  # US Letter at 300 dpi
LINES = [
    TextLine((150, 300, 1650, 400), (
        TextWord("The", (150, 300, 420, 400)),
        TextWord("quick", (470, 300, 860, 400)),
        TextWord("brown", (910, 300, 1330, 400)),
        TextWord("fox", (1380, 300, 1650, 400)),
    )),
    TextLine((150, 500, 1500, 580), (
        TextWord("naïve", (150, 500, 560, 580)),
        TextWord("café", (610, 500, 960, 580)),
        TextWord("Ünïcödé", (1010, 500, 1500, 580)),
    )),
    TextLine((150, 700, 900, 800), (
        TextWord("日本", (150, 700, 350, 800)),
        TextWord("語", (360, 700, 460, 800)),
        TextWord("テキスト", (470, 700, 900, 800)),
    )),
    # A lone one-glyph word: newer PDFium drops text whose glyph box is empty.
    TextLine((150, 900, 250, 1000), (TextWord("字", (150, 900, 250, 1000)),)),
]
EXPECTED = "The quick brown fox naïve café Ünïcödé 日本語テキスト 字"
TERMS = ["quick brown", "café Ünïcödé", "日本語", "fox naïve"]


def run(*args: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYJPDFIUM")}
    done = subprocess.run([sys.executable, "-I", str(RUNNER), *args], capture_output=True,
                          text=True, env=env, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def squash(text: str) -> str:
    return " ".join(text.split())


def write_pdf(path: Path, page_extra: str, content: str) -> Path:
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
    path.write_bytes(bytes(out))
    return path


def is_cjk(word: TextWord) -> bool:
    return all(0x3000 <= ord(c) <= 0x9FFF for c in word.text)


def expected_boxes(lines, to_page):
    """Each non-space character's word box, in page points; CJK runs stretch to the next word."""
    boxes = []
    for line in lines:
        for i, word in enumerate(line.words):
            x0, _, x1, _ = word.box
            following = line.words[i + 1] if i + 1 < len(line.words) else None
            if following is not None and is_cjk(word) and is_cjk(following):
                x1 = following.box[0]
            box = to_page(x0, line.box[1], x1, line.box[3])
            boxes.extend([(c, box) for c in word.text])
    return boxes


def upright(x0, y0, x1, y1, height=IMAGE[1]):
    return x0 * SCALE, (height - y1) * SCALE, x1 * SCALE, (height - y0) * SCALE


# PDFium rounds glyph boxes: tops come out about 0.012 em high in pypdfium2's build.
EM_SLACK = 0.02


def check_placement(chars, expected, tolerance=0.05):
    """Characters sit inside their word box, and each word's characters span it edge to edge."""
    found = [c for c in chars if not c[1] and not c[0].isspace()]
    assert [c[0] for c in found] == [c for c, _ in expected]
    spans = {}
    for (char, _, left, bottom, right, top), (_, (bl, bb, br, bt)) in zip(found, expected):
        slack = EM_SLACK * (bt - bb)
        assert bl - tolerance <= left <= right <= br + tolerance, char
        assert abs(bottom - bb) <= slack and abs(top - bt) <= slack, char
        span = spans.setdefault((bl, bb, br, bt), [left, right])
        span[0], span[1] = min(span[0], left), max(span[1], right)
    for (bl, _, br, _), (left, right) in spans.items():
        assert abs(left - bl) <= tolerance and abs(right - br) <= tolerance


@pytest.fixture
def layer(tmp_path: Path) -> Path:
    path = tmp_path / "layer.pdf"
    pyjpdfium.write_text_layer(path, LINES, image_size=IMAGE, dpi=DPI)
    return path


def test_independent_pdfium_reads_text_search_and_placement(layer):
    result = run("probe", str(layer), *TERMS)
    assert result["size"] == pytest.approx([612, 792], abs=1e-3)
    assert squash(result["text"]) == EXPECTED
    # Word spaces are real characters, so extractors without layout analysis keep them too:
    # three between words and one closing each of the two Latin lines.
    assert sum(1 for c in result["chars"] if c[0] == " " and not c[1]) == 7
    assert result["search"] == {term: 1 for term in TERMS}
    assert result["blank"], "the layer must not draw anything"
    check_placement(result["chars"], expected_boxes(LINES, upright))


def test_qpdf_and_fonttools_accept_the_file(layer):
    result = run("font", str(layer))
    assert result["problems"] == []
    assert result["whole_font_checksum_ok"]
    assert result["contours"] == [2, 2], "blank point contours, as in OCRmyPDF's Occulta"
    assert result["units_per_em"] == 1000
    assert (result["ascent"], result["descent"]) == (800, -200)
    assert {"cmap", "glyf", "head", "hhea", "hmtx", "loca", "maxp", "name", "post"} <= set(
        result["tables"])


def base_page(tmp_path: Path, rotate: int = 0) -> Path:
    # Visible artwork only, so all extracted text comes from the grafted layer.
    content = "0 0 0 rg 72 600 100 100 re f 0.5 g 300 200 150 80 re f"
    extra = "/MediaBox [0 0 612 792]" + (f" /Rotate {rotate}" if rotate else "")
    return write_pdf(tmp_path / f"base{rotate}.pdf", extra, content)


def graft(tmp_path: Path, base: Path, text: Path, **extra) -> Path:
    output = tmp_path / f"grafted-{base.stem}.pdf"
    request = {"base": str(base), "text": str(text), "output": str(output), **extra}
    assert run("graft", SOURCE, json.dumps(request))["grafted"]
    return output


def test_ocrmypdf_sandwich_graft_adds_text_and_nothing_visible(tmp_path, layer):
    base = base_page(tmp_path)
    stripped = tmp_path / "stripped.pdf"
    grafted = graft(tmp_path, base, layer, stripped=str(stripped))
    before, after = run("probe", str(base)), run("probe", str(grafted), *TERMS)
    assert after["render"] == before["render"], "grafting changed what the page shows"
    assert squash(after["text"]) == EXPECTED
    assert after["search"] == {term: 1 for term in TERMS}
    check_placement(after["chars"], expected_boxes(LINES, upright))
    # OCRmyPDF's --redo-ocr strips render-mode-3 text; ours must come out cleanly.
    cleaned = run("probe", str(stripped))
    assert squash(cleaned["text"]) == ""
    assert cleaned["render"] == before["render"]


def test_graft_onto_a_rotated_page_follows_the_displayed_image(tmp_path):
    # OCRmyPDF rasterizes /Rotate 90 pages as displayed, so the image is landscape.
    layer = tmp_path / "landscape.pdf"
    pyjpdfium.write_text_layer(layer, LINES, image_size=(IMAGE[1], IMAGE[0]), dpi=DPI)
    grafted = graft(tmp_path, base_page(tmp_path, rotate=90), layer)
    result = run("probe", str(grafted), *TERMS)
    assert result["rotation"] == 90
    assert squash(result["text"]) == EXPECTED

    def rotated(x0, y0, x1, y1):
        # Displayed top-left (x, y) is unrotated page point (u = y, v = x) under /Rotate 90.
        return y0 * SCALE, x0 * SCALE, y1 * SCALE, x1 * SCALE

    found = [c for c in result["chars"] if not c[1] and not c[0].isspace()]
    for (char, _, left, bottom, right, top), (_, box) in zip(found,
                                                              expected_boxes(LINES, rotated)):
        bl, bb, br, bt = box
        slack = EM_SLACK * (br - bl)  # the line height runs along x once rotated
        assert bl - slack <= left and right <= br + slack, char
        assert bb - 0.05 <= bottom and top <= bt + 0.05, char
