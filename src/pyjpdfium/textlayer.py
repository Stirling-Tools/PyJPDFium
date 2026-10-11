"""Invisible text layers, the text-only PDF of OCRmyPDF's generate_pdf hook, written natively."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Union

from ._loader import native
from .errors import InvalidArgumentError
from .models import Box, TextLine

StrPath = Union[str, "os.PathLike[str]"]
Dpi = Union[float, "tuple[float, float]"]


def _box(box: Box) -> Box:
    x0, y0, x1, y1 = box
    return float(x0), float(y0), float(x1), float(y1)


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
    OCRmyPDF's renderer does. Right-to-left text raises UnsupportedError for now. On any failure
    ``output`` is left untouched.
    """
    native_lines: list[tuple[Box, int]] = []
    native_words: list[tuple[str, Box]] = []
    for line in lines:
        native_lines.append((_box(line.box), len(line.words)))
        native_words.extend((_text(word.text), _box(word.box)) for word in line.words)
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
