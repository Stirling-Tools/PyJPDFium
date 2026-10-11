"""Python bindings to JPDFium's native PDF core. No JVM required.

Importing this package loads no native library. The core loads on first use, for example
``open_document``.
"""

from __future__ import annotations

import importlib
from typing import Any

__version__ = "0.1.0.dev0"

_EXPORTS = {
    "open_document": "pyjpdfium.pdf",
    "Document": "pyjpdfium.pdf",
    "Page": "pyjpdfium.pdf",
    "Bitmap": "pyjpdfium.pdf",
    "rasterize_page": "pyjpdfium.raster",
    "write_text_layer": "pyjpdfium.textlayer",
    "runtime_info": "pyjpdfium.runtime",
    "capability": "pyjpdfium.runtime",
    "quiesce": "pyjpdfium.runtime",
    "shutdown": "pyjpdfium.runtime",
    "PixelFormat": "pyjpdfium.models",
    "RenderFlags": "pyjpdfium.models",
    "Renderer": "pyjpdfium.models",
    "RuntimeState": "pyjpdfium.models",
    "Capability": "pyjpdfium.models",
    "PageSize": "pyjpdfium.models",
    "BitmapInfo": "pyjpdfium.models",
    "RuntimeInfo": "pyjpdfium.models",
    "RasterDevice": "pyjpdfium.models",
    "RasterResult": "pyjpdfium.models",
    "Interpolation": "pyjpdfium.models",
    "Border": "pyjpdfium.models",
    "RectifyResult": "pyjpdfium.models",
    "TextWord": "pyjpdfium.models",
    "TextLine": "pyjpdfium.models",
    "PyJPDFiumError": "pyjpdfium.errors",
    "NativeLoadError": "pyjpdfium.errors",
    "InvalidArgumentError": "pyjpdfium.errors",
    "HandleError": "pyjpdfium.errors",
    "InvalidHandleError": "pyjpdfium.errors",
    "StaleHandleError": "pyjpdfium.errors",
    "WrongHandleTypeError": "pyjpdfium.errors",
    "ResourceBusyError": "pyjpdfium.errors",
    "UnsupportedError": "pyjpdfium.errors",
    "PdfIOError": "pyjpdfium.errors",
    "PasswordError": "pyjpdfium.errors",
    "PdfFormatError": "pyjpdfium.errors",
    "PageNotFoundError": "pyjpdfium.errors",
    "LimitExceededError": "pyjpdfium.errors",
    "NativeMemoryError": "pyjpdfium.errors",
    "RuntimeStateError": "pyjpdfium.errors",
    "ReentrancyError": "pyjpdfium.errors",
    "OperationCancelledError": "pyjpdfium.errors",
    "OperationTimeoutError": "pyjpdfium.errors",
    "InternalError": "pyjpdfium.errors",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'pyjpdfium' has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
