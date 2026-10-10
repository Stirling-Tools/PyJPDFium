"""Value types and enums. Pure Python; loads nothing native."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, IntFlag


class Renderer(IntEnum):
    AUTO = -1
    AGG = 0
    SKIA = 1


class RuntimeState(IntEnum):
    UNINITIALIZED = 0
    RUNNING = 1
    QUIESCING = 2
    DESTROYING = 3
    STOPPED = 4
    FAILED = 5


class Capability(IntEnum):
    ABSENT = 0
    IMPLEMENTED = 1
    QUALIFIED = 2


class PixelFormat(IntEnum):
    RGBA = 1
    RGB = 2
    GRAY = 3

    @property
    def channels(self) -> int:
        return {PixelFormat.RGBA: 4, PixelFormat.RGB: 3, PixelFormat.GRAY: 1}[self]


class RenderFlags(IntFlag):
    NONE = 0
    ANNOTATIONS = 0x0001
    LCD_TEXT = 0x0002
    GRAYSCALE = 0x0004
    PRINTING = 0x0008
    NO_SMOOTH_TEXT = 0x0010
    NO_SMOOTH_IMAGE = 0x0020
    NO_SMOOTH_PATH = 0x0040
    TRANSPARENT = 0x0100


@dataclass(frozen=True)
class PageSize:
    """Displayed page size in points, after /Rotate."""

    width: float
    height: float


@dataclass(frozen=True)
class BitmapInfo:
    width: int
    height: int
    stride: int
    pixel_format: PixelFormat
    dpi: tuple[float, float]
    byte_size: int


@dataclass(frozen=True)
class RuntimeInfo:
    state: RuntimeState
    api_version: tuple[int, int]
    renderer: Renderer | None
    build_id: str
    live_documents: int
    live_pages: int
    live_bitmaps: int
    live_views: int
    domain_acquisitions: int
    domain_wait_ns: int
    domain_hold_ns: int


class RasterDevice(IntEnum):
    """Native raster devices, named after the Ghostscript devices OCRmyPDF requests."""

    PNGMONO = 1
    PNGMONOD = 2
    PNGGRAY = 3
    PNG256 = 4  # written as 24-bit RGB; no palette quantization
    PNG16M = 5
    PNGALPHA = 6  # opaque white background, so written as RGB like the reference


class Interpolation(IntEnum):
    NEAREST = 0
    BILINEAR = 1
    BICUBIC = 2  # OpenCV INTER_CUBIC kernel


class Border(IntEnum):
    WHITE = 0
    REPLICATE = 1


@dataclass(frozen=True)
class RasterResult:
    width: int
    height: int
    bits_per_pixel: int
    dpi: tuple[float, float]


@dataclass(frozen=True)
class RectifyResult:
    """Corners as used (top-left, top-right, bottom-right, bottom-left) and the inverse map."""

    quad: tuple[tuple[float, float], ...]
    to_source: tuple[float, ...]  # row-major 3x3, output pixel -> source pixel

    def map_to_source(self, x: float, y: float) -> tuple[float, float]:
        h = self.to_source
        w = h[6] * x + h[7] * y + h[8]
        return (h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w
