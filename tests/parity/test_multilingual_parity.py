"""Multilingual qualification: scripts, directions and rotations read back by independent tools.

Opt-in like the other parity tests. Each layer is read by pypdfium2's PDFium, pdfminer.six and
poppler's pdftotext when present, and by our own PDFium. Text must reach the floor recorded for
that tool and layout in docs/COMPATIBILITY.md; character boxes must land in the writer's cells.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

import pyjpdfium
from pyjpdfium import TextLine, TextWord

from test_text_layer_parity import write_pdf

SOURCE = os.environ.get("PYJPDFIUM_PARITY_SRC")
RUNNER = Path(__file__).with_name("text_layer_runner.py")
pytestmark = [
    pytest.mark.native,
    pytest.mark.skipif(not SOURCE, reason="PYJPDFIUM_PARITY_SRC is not set"),
]

DPI = 300.0
SCALE = 72.0 / DPI
IMAGE = (2550, 3300)
CELL = 50.0  # px per code point, the glyphless font's own width on a 100 px line
GAP = 40.0
HEIGHT = 100.0


@dataclass(frozen=True)
class Sample:
    name: str
    text: str
    kind: str  # "ltr", "rtl" or "mixed"
    rtl_line: bool = False


SAMPLES = [
    Sample("latin", "The quick brown fox", "ltr"),
    Sample("greek", "Καλημέρα κόσμε", "ltr"),
    Sample("cyrillic", "Привет мир", "ltr"),
    Sample("chinese", "中文 文本", "ltr"),
    Sample("hangul", "안녕하세요 세계", "ltr"),
    Sample("kana", "ひらがな カタカナ", "ltr"),
    Sample("devanagari", "नमस्ते दुनिया", "ltr"),
    Sample("thai", "สวัสดี ชาวโลก", "ltr"),
    Sample("latin_combining", "cafe\u0301 nai\u0308ve", "ltr"),
    Sample("emoji", "\U0001f44d\U0001f3fd \U0001f468\u200d\U0001f469\u200d\U0001f467 "
                    "\U0001f1e9\U0001f1ea", "ltr"),
    Sample("digits", "3.14 $100 (a)", "ltr"),
    Sample("hebrew", "שלום עולם", "rtl", True),
    Sample("hebrew_niqqud", "שָׁלוֹם עוֹלָם", "rtl", True),
    Sample("arabic", "مرحبا بالعالم", "rtl", True),
    Sample("arabic_harakat", "مَرْحَبًا يَا", "rtl", True),
    Sample("persian_zwnj", "می\u200cخواهم بروم", "rtl", True),
    Sample("hebrew_digits", "עמוד 12 מתוך 30", "mixed", True),
    Sample("hebrew_word_digits", "עמוד12", "mixed", True),
    Sample("arabic_indic_digits", "سنة ٢٠٢٤", "mixed", True),
    Sample("rtl_brackets", "(שלום) [עולם]", "mixed", True),
    Sample("ltr_with_hebrew", "see שלום here", "mixed"),
    Sample("rtl_with_latin", "שלום world עולם", "mixed", True),
    Sample("rtl_with_cjk", "שלום 日本 語", "mixed", True),  # unspaced CJK in a right-to-left line
]
LAYOUTS = {"flat": (0.0, 0.0), "rot15": (15.0, 0.0), "rot90": (90.0, 0.0),
           "rot180": (180.0, 0.0), "skew": (0.0, 30.0)}
RANK = {"lost": 0, "chars": 1, "words": 2, "nfc": 3, "exact": 4}


def cjk(text: str) -> bool:
    return all(0x3000 <= ord(c) <= 0x9FFF or 0xAC00 <= ord(c) <= 0xD7AF for c in text)


def expected_text(sample: Sample) -> str:
    words = sample.text.split(" ")
    out = words[0]
    for previous, word in zip(words, words[1:]):
        out += ("" if cjk(previous) and cjk(word) else " ") + word
    return out


def corners(box):
    x0, y0, x1, y1 = box
    return (x0, y0), (x1, y0), (x1, y1), (x0, y1)


def build(sample: Sample, angle: float, skew: float) -> TextLine:
    """One line, words placed in reading order; rotated or skewed lines become quads."""
    words = sample.text.split(" ")
    widths = [CELL * len(w) for w in words]
    total = sum(widths) + GAP * (len(words) - 1)
    x0, y0 = 400.0, 1500.0
    cx, cy = x0 + total / 2, y0 + HEIGHT / 2
    a = math.radians(angle)

    def quad(box):
        bx0, by0, bx1, by1 = box
        points = ((bx0 + skew, by0), (bx1 + skew, by0), (bx1, by1), (bx0, by1))
        return tuple((cx + (x - cx) * math.cos(a) - (y - cy) * math.sin(a),
                      cy + (x - cx) * math.sin(a) + (y - cy) * math.cos(a)) for x, y in points)

    placed = []
    x = x0 + total if sample.rtl_line else x0
    for text, width in zip(words, widths):
        left = x - width if sample.rtl_line else x
        box = (left, y0, left + width, y0 + HEIGHT)
        x += -(width + GAP) if sample.rtl_line else width + GAP
        placed.append((text, box))
    line_box = (x0, y0, x0 + total, y0 + HEIGHT)
    if angle == 0 and skew == 0:
        return TextLine(line_box, tuple(TextWord(t, b) for t, b in placed))
    return TextLine(line_box, tuple(TextWord(t, b, quad(b)) for t, b in placed), quad(line_box))


def to_page(point):
    return point[0] * SCALE, (IMAGE[1] - point[1]) * SCALE


def expected_cells(line: TextLine, rtl: bool):
    """Where each emitted character's box centre must land, in page points: the writer contract.

    Words of one strong direction are checked character by character; mixed words, which the full
    bidi algorithm lays out, are checked to stay inside their word.
    """
    q = [to_page(p) for p in (line.quad or corners(line.box))]
    u = ((q[1][0] - q[0][0] + q[2][0] - q[3][0]) / 2, (q[1][1] - q[0][1] + q[2][1] - q[3][1]) / 2)
    w = ((q[0][0] - q[3][0] + q[1][0] - q[2][0]) / 2, (q[0][1] - q[3][1] + q[1][1] - q[2][1]) / 2)
    size = math.hypot(*w)
    u = (u[0] / math.hypot(*u), u[1] / math.hypot(*u))
    w = (w[0] / size, w[1] / size)
    det = u[0] * w[1] - u[1] * w[0]
    base = q[3]

    def along(p):
        return ((p[0] - base[0]) * w[1] - (p[1] - base[1]) * w[0]) / det

    def point(s):
        return base[0] + s * u[0] + size / 2 * w[0], base[1] + s * u[1] + size / 2 * w[1]

    spans = []
    for word in line.words:
        values = [along(to_page(p)) for p in (word.quad or corners(word.box))]
        spans.append((min(values), max(values)))
    cells, loose = [], []
    for i, word in enumerate(line.words):
        lo, hi = spans[i]
        n = len(word.text)
        cell = (hi - lo) / n
        if i + 1 < len(line.words):
            step = hi - spans[i + 1][1] if rtl else spans[i + 1][0] - lo
            both = cjk(word.text) and cjk(line.words[i + 1].text)
            space = step > 0 and not both
            if both and 0 < step and step - (hi - lo) <= 2 * size:
                cell *= step / (hi - lo)
        else:
            space = not word.text.isspace() and not cjk(word.text)
        start = hi - n * cell if rtl else lo
        classes = {unicodedata.bidirectional(c) for c in word.text} - {"NSM"}
        if "R" in classes or "AL" in classes or "AN" in classes:
            order = range(n - 1, -1, -1) if classes <= {"R", "AL"} else None
        else:
            order = range(n) if not rtl or classes <= {"L"} else None
        if order is None:
            loose.extend((c, point(start + n * cell / 2), n * cell / 2) for c in word.text)
        else:
            cells.extend((word.text[k], point(start + (slot + 0.5) * cell), cell)
                         for k, slot in zip(range(n), order))
        if space:
            s = start - cell / 2 if rtl else start + (n + 0.5) * cell
            cells.append((" ", point(s), cell))
    return cells, loose


def reached(got: str, sample: Sample) -> str:
    """exact, then equal after NFC, then the same words in any order, then the same characters."""
    got, want = " ".join(got.split()), expected_text(sample)
    if got == want:
        return "exact"
    nfc_got, nfc_want = (unicodedata.normalize("NFC", s) for s in (got, want))
    if nfc_got == nfc_want:
        return "nfc"
    words = [unicodedata.normalize("NFC", w) for w in sample.text.split(" ")]
    if sorted(nfc_got.split()) in (sorted(nfc_want.split()), sorted(words)):
        return "words"
    nfd_got, nfd_want = (unicodedata.normalize("NFD", s).replace(" ", "") for s in (got, want))
    if Counter(nfd_got) == Counter(nfd_want):
        return "chars"
    return "lost"


def floor(tool: str, sample: Sample, layout: str) -> str:
    """The weakest result each tool showed in the qualification run (docs/COMPATIBILITY.md)."""
    rotated = layout in ("rot15", "rot90", "rot180")
    if tool == "pdfminer":
        # pdfminer reads stream order, but splits vertical text into single characters.
        if layout == "rot90" or (sample.kind == "mixed" and layout == "rot180"):
            return "chars"
        return "words" if sample.kind == "mixed" else "exact"
    if sample.kind == "mixed":
        return "chars"  # PDFium and poppler re-derive order and spaces at a direction change
    if tool == "poppler":
        if layout == "rot15" or (layout == "rot180" and sample.kind == "rtl"):
            return "chars"  # poppler splits words on slanted or upside-down right-to-left lines
        return "exact"
    # PDFium orders the words of upside-down lines, and of rotated right-to-left ones, by page
    # position; it can also reorder Hebrew points, which NFC undoes.
    if sample.kind == "rtl":
        return "words" if rotated else "nfc"
    return "words" if layout == "rot180" else "exact"


def run(*args: str):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYJPDFIUM")}
    done = subprocess.run([sys.executable, "-I", str(RUNNER), *args], capture_output=True,
                          text=True, env=env, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@dataclass
class Case:
    sample: Sample
    layout: str
    line: TextLine
    path: Path
    texts: dict
    chars: list


@pytest.fixture(scope="module")
def cases(tmp_path_factory) -> list[Case]:
    root = tmp_path_factory.mktemp("multilingual")
    built = []
    for sample in SAMPLES:
        for layout, (angle, skew) in LAYOUTS.items():
            line = build(sample, angle, skew)
            path = root / f"{sample.name}-{layout}.pdf"
            pyjpdfium.write_text_layer(path, [line], image_size=IMAGE, dpi=DPI)
            built.append((sample, layout, line, path))
    extracted = run("extract", *(str(path) for *_, path in built))
    pdftotext = shutil.which("pdftotext")
    out = []
    for (sample, layout, line, path), found in zip(built, extracted):
        with pyjpdfium.open_document(path) as document, document.page(0) as page:
            texts = {"ours": page.text(), "pypdfium2": found["pdfium"]}
        if found["pdfminer"] is not None:
            texts["pdfminer"] = found["pdfminer"]
        if pdftotext:
            raw = subprocess.run([pdftotext, "-enc", "UTF-8", str(path), "-"], capture_output=True,
                                 text=True, check=True).stdout
            texts["poppler"] = "".join(c for c in raw if c not in "\u202a\u202b\u202c\u202d\u202e")
        out.append(Case(sample, layout, line, path, texts, found["chars"]))
    return out


@pytest.mark.parametrize("tool", ["ours", "pypdfium2", "pdfminer", "poppler"])
def test_extracted_text_reaches_its_floor(cases, tool):
    if tool not in cases[0].texts:
        pytest.skip(f"{tool} is not installed")
    misses = []
    for case in cases:
        got = reached(case.texts[tool], case.sample)
        need = floor(tool, case.sample, case.layout)
        if RANK[got] < RANK[need]:
            misses.append(f"{case.sample.name}/{case.layout}: {got} < {need}: "
                          f"{case.texts[tool]!r}")
    assert not misses, "\n".join(misses)


def test_horizontal_right_to_left_lines_are_exact_where_it_matters(cases):
    # The gate's core claim: logical text from PDFium and stream-order readers alike.
    for case in cases:
        if case.sample.kind == "rtl" and case.layout in ("flat", "skew"):
            for tool in ("ours", "pypdfium2", "pdfminer"):
                if tool in case.texts:
                    assert reached(case.texts[tool], case.sample) in ("exact", "nfc"), (
                        tool, case.sample.name, case.layout)


def test_characters_land_in_their_cells(cases):
    misses = []
    for case in cases:
        cells, loose = expected_cells(case.line, case.sample.rtl_line)
        found = [(c[0], ((c[2] + c[4]) / 2, (c[3] + c[5]) / 2)) for c in case.chars if not c[1]]
        # A cell's centre within a quarter cell; a mixed word's characters within the word.
        targets = [(c, p, cell / 4) for c, p, cell in cells] + loose
        if case.sample.kind == "mixed":
            # PDFium merges or drops spaces at a direction change, so only letters are held.
            found = [f for f in found if not f[0].isspace()]
            targets = [t for t in targets if not t[0].isspace()]
        if len(found) != len(targets):
            misses.append(f"{case.sample.name}/{case.layout}: {len(found)} characters, "
                          f"want {len(targets)}")
            continue
        unused = list(found)
        for char, (x, y), limit in targets:
            hit = next((f for f in unused if f[0] == char and
                        math.hypot(f[1][0] - x, f[1][1] - y) <= limit), None)
            if hit is None:
                misses.append(f"{case.sample.name}/{case.layout}: {char!r} not at its cell")
            else:
                unused.remove(hit)
    assert not misses, "\n".join(misses)


def test_multilingual_layers_draw_nothing_and_survive_ocrmypdfs_graft(tmp_path):
    lines = [build(SAMPLES[11], 0, 0), build(SAMPLES[0], 90, 0), build(SAMPLES[13], 0, 30)]
    # Spread the three lines down the page so they never overlap.
    moved = []
    for n, line in enumerate(lines):
        dy = (n - 1) * 600.0
        shift = (lambda q: tuple((x, y + dy) for x, y in q)) if line.quad else None
        words = tuple(TextWord(w.text, (w.box[0], w.box[1] + dy, w.box[2], w.box[3] + dy),
                               shift(w.quad) if shift else None) for w in line.words)
        box = (line.box[0], line.box[1] + dy, line.box[2], line.box[3] + dy)
        moved.append(TextLine(box, words, shift(line.quad) if shift else None))
    layer = tmp_path / "layer.pdf"
    pyjpdfium.write_text_layer(layer, moved, image_size=IMAGE, dpi=DPI)
    before = run("probe", str(layer))
    assert before["blank"], "the layer must not draw anything"
    base = write_pdf(tmp_path / "base.pdf", "/MediaBox [0 0 612 792]", "0.5 g 0 0 150 80 re f")
    output = tmp_path / "grafted.pdf"
    request = {"base": str(base), "text": str(layer), "output": str(output)}
    assert run("graft", SOURCE, json.dumps(request))["grafted"]
    after = run("probe", str(output))
    assert " ".join(after["text"].split()) == " ".join(before["text"].split())
    assert after["render"] == run("probe", str(base))["render"], "the graft changed the page"
