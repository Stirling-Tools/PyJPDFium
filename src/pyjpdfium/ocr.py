"""OCR with PP-OCR models on ONNX Runtime, in JPDFium's optional native OCR module.

The module and its models load on first use. A profile directory holds the models it pins, as
fetched by JPDFium's native/ocr/tools/fetch_profile.py; every file is checked against its
digest when an engine opens.
"""

from __future__ import annotations

import os
from typing import Union

from ._loader import ocr_native
from .errors import InvalidArgumentError
from .models import OcrLine, OcrResult
from .pdf import Bitmap, _Handle, load_image

StrPath = Union[str, "os.PathLike[str]"]


class OcrEngine(_Handle):
    """A verified profile with its two models loaded. Safe to share across threads."""

    def __init__(self, profile: StrPath, *, threads: int = 0) -> None:
        if threads < 0:
            raise InvalidArgumentError("threads must not be negative")
        lib = ocr_native()
        token = lib.engine_open(os.fsdecode(os.fspath(profile)), threads)
        super().__init__(token, lib.engine_close)
        self.profile, self.runtime_version = lib.engine_info(self._require_open())

    def recognize(self, image: Bitmap | StrPath, *, max_pixels: int | None = None) -> OcrResult:
        """Recognizes a Bitmap, or a PNG file loaded as OpenCV's imread would read it."""
        self._require_open()
        if isinstance(image, Bitmap):
            return self._recognize(image, max_pixels)
        with load_image(image) as bitmap:
            return self._recognize(bitmap, max_pixels)

    def _recognize(self, bitmap: Bitmap, max_pixels: int | None) -> OcrResult:
        width, height, dpi_x, dpi_y, lines = ocr_native().recognize(
            self._require_open(), bitmap._require_open(), max_pixels or 0
        )
        return OcrResult(
            image_size=(width, height),
            dpi=(dpi_x, dpi_y),
            profile=self.profile,
            lines=tuple(
                OcrLine(text, tuple(zip(poly[0::2], poly[1::2])), confidence, score)
                for text, poly, confidence, score in lines
            ),
        )

    def __repr__(self) -> str:
        state = "closed" if self.closed else "open"
        return f"<OcrEngine {self.profile!r} {state}>"


def recognize_image(path: StrPath, *, profile: StrPath, threads: int = 0) -> OcrResult:
    """One-off recognition; keep an OcrEngine for many images, since opening one loads models."""
    with OcrEngine(profile, threads=threads) as engine:
        return engine.recognize(path)
