"""Page rasterization with OCRmyPDF's rasterize_pdf_page contract, done natively."""

from __future__ import annotations

import os
from typing import Union

from ._loader import native
from .errors import UnsupportedError
from .models import RasterDevice, RasterResult

StrPath = Union[str, "os.PathLike[str]"]
Dpi = Union[float, "tuple[float, float]"]

_USE_CROPBOX = 0x0001
_FILTER_VECTOR = 0x0002

# Ghostscript devices OCRmyPDF may request that this rasterizer does not produce.
_NOT_PRODUCED = {"jpeg", "jpeggray", "jpg", "tiff", "tif"}


def _device(device: RasterDevice | str) -> RasterDevice:
    if isinstance(device, RasterDevice):
        return device
    name = device.lower()
    if name in _NOT_PRODUCED:
        raise UnsupportedError(f"raster device {device!r} needs a JPEG or TIFF encoder")
    try:
        return RasterDevice[name.upper()]
    except KeyError:
        raise UnsupportedError(f"unknown raster device {device!r}") from None


def _pair(dpi: Dpi) -> tuple[float, float]:
    if isinstance(dpi, (int, float)):
        return float(dpi), float(dpi)
    x, y = dpi
    return float(x), float(y)


def rasterize_page(
    path: StrPath,
    page_index: int,
    output: StrPath,
    *,
    device: RasterDevice | str = RasterDevice.PNG16M,
    raster_dpi: Dpi = 300.0,
    output_dpi: Dpi | None = None,
    rotation: int = 0,
    use_cropbox: bool = False,
    filter_vector: bool = False,
    password: str | None = None,
    max_pixels: int | None = None,
    durable: bool = False,
    png_compression: int | None = None,
    max_bytes: int | None = None,
) -> RasterResult:
    """Rasterizes one page (0-based) to a PNG, published atomically.

    ``rotation`` is a counterclockwise correction in quarter turns, applied on top of the page's
    own /Rotate as Ghostscript does. ``output_dpi`` sets only the DPI written to the file.
    """
    dpi_x, dpi_y = _pair(raster_dpi)
    out_x, out_y = _pair(output_dpi) if output_dpi is not None else (0.0, 0.0)
    flags = (_USE_CROPBOX if use_cropbox else 0) | (_FILTER_VECTOR if filter_vector else 0)
    width, height, bpp, rx, ry = native().rasterize_page_file(
        os.fsdecode(os.fspath(path)),
        page_index,
        int(_device(device)),
        dpi_x,
        dpi_y,
        out_x,
        out_y,
        rotation % 360,
        flags,
        max_pixels or 0,
        password,
        os.fsdecode(os.fspath(output)),
        durable,
        -1 if png_compression is None else png_compression,
        max_bytes or 0,
    )
    return RasterResult(width, height, bpp, (rx, ry))
