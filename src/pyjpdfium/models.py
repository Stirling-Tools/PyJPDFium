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
