"""Invisible text layers, the text-only PDF of OCRmyPDF's generate_pdf hook, written natively."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Union

from ._loader import native
from .errors import InvalidArgumentError
from .models import Box, Quad, TextLine

StrPath = Union[str, "os.PathLike[str]"]
Dpi = Union[float, "tuple[float, float]"]


def _box(box: Box) -> Box:
    x0, y0, x1, y1 = box
    return float(x0), float(y0), float(x1), float(y1)


_QUAD = 0x1
_LTR = 0x2
_RTL = 0x4
_DIRECTIONS = {"auto": 0, "ltr": _LTR, "rtl": _RTL}
_NO_QUAD = (0.0,) * 8


def _quad(quad: Quad | None) -> tuple[int, tuple[float, ...]]:
    if quad is None:
        return 0, _NO_QUAD
    points = tuple(quad)
    if len(points) != 4:
        raise InvalidArgumentError("a quad has four corners")
    return _QUAD, tuple(float(v) for point in points for v in point)


def _line_flags(line: TextLine) -> tuple[int, tuple[float, ...]]:
    flags, quad = _quad(line.quad)
    try:
        return flags | _DIRECTIONS[line.direction], quad
    except KeyError:
        raise InvalidArgumentError("direction must be 'auto', 'ltr' or 'rtl'") from None


def _text(text: str) -> str:
    # The native side takes NUL-terminated UTF-8, so these could not reach it intact.
    if "\x00" in text:
        raise InvalidArgumentError("word text contains a NUL character")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidArgumentError("word text is not valid Unicode") from None
    return text


def write_text_layer(
    output: StrPath,
    lines: Iterable[TextLine],
    *,
    image_size: tuple[int, int],
    dpi: Dpi,
    durable: bool = False,
    max_bytes: int | None = None,
) -> None:
    """Publishes a one-page PDF sized to the image, holding only invisible, extractable text.

    Each word is stretched to its box and gets a trailing space, except between CJK words, as
    OCRmyPDF's renderer does. Right-to-left and mixed-direction words stay in logical order and
    are placed by the Unicode bidi algorithm; quads place rotated or skewed lines. On any failure
    ``output`` is left untouched.
    """
    native_lines: list[tuple[Box, int, int, tuple[float, ...]]] = []
    native_words: list[tuple[str, Box, int, tuple[float, ...]]] = []
    for line in lines:
        native_lines.append((_box(line.box), len(line.words), *_line_flags(line)))
        native_words.extend(
            (_text(word.text), _box(word.box), *_quad(word.quad)) for word in line.words
        )
    width, height = image_size
    dpi_x, dpi_y = (float(dpi), float(dpi)) if isinstance(dpi, (int, float)) else map(float, dpi)
    native().text_layer_write(
        os.fsdecode(os.fspath(output)),
        int(width),
        int(height),
        dpi_x,
        dpi_y,
        native_lines,
        native_words,
        durable,
        max_bytes or 0,
    )
