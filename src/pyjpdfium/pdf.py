"""Documents, pages and rendered bitmaps over the native core's generation-checked handles."""

from __future__ import annotations

import os
import threading
import weakref
from collections.abc import Callable, Sequence
from typing import Union

from ._loader import native
from .errors import InvalidArgumentError, PyJPDFiumError, StaleHandleError
from .models import (
    BitmapInfo,
    Border,
    Interpolation,
    PageSize,
    PixelFormat,
    RectifyResult,
    RenderFlags,
)

StrPath = Union[str, "os.PathLike[str]"]
Dpi = Union[float, "tuple[float, float]"]

# 0 asks the native core for its default pixel budget, and for no byte limit on output.
_LIBRARY_BUDGET = 0
_NO_LIMIT = 0


def _fspath(path: StrPath) -> str:
    return os.fsdecode(os.fspath(path))


def _close_quietly(close: Callable[[int], None], token: int) -> None:
    # Finalizers only reclaim what was never closed; they must not raise.
    try:
        close(token)
    except PyJPDFiumError:
        pass


class _Handle:
    """Idempotent close over one native token; finalization covers objects never closed."""

    def __init__(self, token: int, close: Callable[[int], None]) -> None:
        self._token = token
        self._finalizer = weakref.finalize(self, _close_quietly, close, token)
        self._close = close
        self._close_lock = threading.Lock()

    @property
    def closed(self) -> bool:
        return not self._finalizer.alive

    def _require_open(self) -> int:
        if self.closed:
            raise StaleHandleError(f"{type(self).__name__} is closed")
        return self._token

    def close(self) -> None:
        with self._close_lock:
            if self.closed:
                return
            # BUSY propagates and leaves this object open, matching the native contract.
            self._close(self._token)
            self._finalizer.detach()

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def open_document(path: StrPath, *, password: str | None = None) -> Document:
    lib = native()
    return Document(lib.doc_open(_fspath(path), password), _fspath(path))


def load_image(path: StrPath, *, max_pixels: int | None = None) -> Bitmap:
    """Decodes a PNG into a Bitmap: gray stays gray, colour becomes RGB, alpha is dropped."""
    return Bitmap(native().image_load(_fspath(path), max_pixels or 0))


class Document(_Handle):
    def __init__(self, token: int, path: str) -> None:
        super().__init__(token, native().doc_close)
        self.path = path

    @property
    def page_count(self) -> int:
        return native().doc_page_count(self._require_open())

    def page(self, index: int) -> Page:
        token = native().page_open(self._require_open(), index)
        return Page(token, self)

    def close(self) -> None:
        """Raises ResourceBusyError while pages are open; the document stays usable."""
        super().close()

    def __repr__(self) -> str:
        state = "closed" if self.closed else "open"
        return f"<Document {self.path!r} {state}>"


def _dpi_pair(dpi: Dpi) -> tuple[float, float]:
    if isinstance(dpi, (int, float)):
        return float(dpi), float(dpi)
    x, y = dpi
    return float(x), float(y)


def _render_args(
    dpi: Dpi,
    size: tuple[int, int] | None,
    pixel_format: PixelFormat | str,
    annotations: bool,
    transparent: bool,
    flags: RenderFlags,
    max_pixels: int | None,
) -> tuple[int, float, float, int, int, int, int]:
    fmt = PixelFormat[pixel_format.upper()] if isinstance(pixel_format, str) else pixel_format
    all_flags = RenderFlags(flags)
    if annotations:
        all_flags |= RenderFlags.ANNOTATIONS
    if transparent:
        all_flags |= RenderFlags.TRANSPARENT
    dpi_x, dpi_y = _dpi_pair(dpi)
    width, height = size if size is not None else (0, 0)
    if max_pixels is not None and max_pixels <= 0:
        raise InvalidArgumentError("max_pixels must be positive")
    return (
        int(all_flags),
        dpi_x,
        dpi_y,
        width,
        height,
        int(fmt),
        max_pixels or _LIBRARY_BUDGET,
    )


class Page(_Handle):
    def __init__(self, token: int, document: Document) -> None:
        super().__init__(token, native().page_close)
        # A page keeps its document alive, mirroring the native parent retention.
        self.document = document
        index, width, height, rotation = native().page_info(token)
        self.index = index
        self.size = PageSize(width, height)
        self.rotation = rotation

    def render(
        self,
        path: StrPath | None = None,
        *,
        dpi: Dpi = 72.0,
        size: tuple[int, int] | None = None,
        pixel_format: PixelFormat | str = PixelFormat.RGB,
        annotations: bool = True,
        transparent: bool = False,
        flags: RenderFlags = RenderFlags.NONE,
        max_pixels: int | None = None,
        durable: bool = False,
        png_compression: int | None = None,
        max_bytes: int | None = None,
    ) -> Bitmap | None:
        """Renders to a Bitmap, or publishes a PNG at ``path`` and returns None.

        File output is transactional: on any failure ``path`` is left untouched.
        """
        args = _render_args(dpi, size, pixel_format, annotations, transparent, flags, max_pixels)
        token = self._require_open()
        if path is None:
            return Bitmap(native().page_render(token, *args))
        native().page_render_to_file(
            token,
            *args,
            _fspath(path),
            durable,
            -1 if png_compression is None else png_compression,
            max_bytes or _NO_LIMIT,
        )
        return None

    def text(self) -> str:
        """The page text in PDFium's extraction order, with its generated spaces and line breaks."""
        return native().page_text(self._require_open())

    def __repr__(self) -> str:
        state = "closed" if self.closed else "open"
        return f"<Page {self.index} of {self.document.path!r} {state}>"


class Bitmap(_Handle):
    """Independently owned pixels: closing the page or document does not affect them."""

    def __init__(self, token: int) -> None:
        super().__init__(token, native().bitmap_close)
        fmt, width, height, stride, dpi_x, dpi_y, byte_size = native().bitmap_info(token)
        self.info = BitmapInfo(width, height, stride, PixelFormat(fmt), (dpi_x, dpi_y), byte_size)

    @property
    def width(self) -> int:
        return self.info.width

    @property
    def height(self) -> int:
        return self.info.height

    @property
    def pixel_format(self) -> PixelFormat:
        return self.info.pixel_format

    def tobytes(self) -> bytes:
        return native().bitmap_copy(self._require_open())

    def view(self) -> memoryview:
        """Zero-copy read-only view, shape (height, width[, channels]).

        The view pins the pixels itself, so it stays valid after this bitmap is closed.
        """
        return memoryview(native().bitmap_view(self._require_open()))

    def save(
        self,
        path: StrPath,
        *,
        durable: bool = False,
        png_compression: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        """Publishes a PNG transactionally; on failure ``path`` is left untouched."""
        native().bitmap_write_file(
            self._require_open(),
            _fspath(path),
            durable,
            -1 if png_compression is None else png_compression,
            max_bytes or _NO_LIMIT,
        )

    def rectify(
        self,
        quad: "Sequence[tuple[float, float]] | Sequence[float]",
        *,
        size: tuple[int, int] | None = None,
        interpolation: Interpolation | str = Interpolation.BILINEAR,
        border: Border | str = Border.WHITE,
        max_pixels: int | None = None,
    ) -> tuple[Bitmap, RectifyResult]:
        """Perspective-corrects a quad (4 corners in source pixels, any order) into a new bitmap.

        Without ``size`` the output takes PaddleOCR's truncated lengths of the longer opposite
        edges. The result maps output pixels back to source pixels.
        """
        values = list(quad)
        if values and isinstance(values[0], (tuple, list)):
            flat = [float(c) for point in values for c in point]
        else:
            flat = [float(v) for v in values]
        if isinstance(interpolation, str):
            interpolation = Interpolation[interpolation.upper()]
        if isinstance(border, str):
            border = Border[border.upper()]
        width, height = size if size is not None else (0, 0)
        token, corners, to_source = native().bitmap_rectify(
            self._require_open(), flat, width, height, int(interpolation), int(border),
            max_pixels or 0,
        )
        points = tuple((corners[i], corners[i + 1]) for i in range(0, 8, 2))
        return Bitmap(token), RectifyResult(points, tuple(to_source))

    def __repr__(self) -> str:
        state = "closed" if self.closed else "open"
        return f"<Bitmap {self.width}x{self.height} {self.pixel_format.name} {state}>"
