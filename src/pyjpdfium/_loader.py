"""Explicit lazy loading of the native core. Nothing here runs at package import."""

from __future__ import annotations

import ctypes
import importlib
import os
import sys
import threading
from pathlib import Path
from types import ModuleType

from .errors import NativeLoadError
from .models import Renderer

NATIVE_DIR_ENV = "PYJPDFIUM_NATIVE_DIR"
RENDERER_ENV = "PYJPDFIUM_RENDERER"
# Sonames other wheels also ship (pypdfium2, onnxruntime); tools/stage_natives.py renames ours.
SHARED_SONAMES = {"libpdfium.so": "libjpdfium_pdfium.so",
                  "libonnxruntime.so.1": "libjpdfium_onnxruntime.so.1"}

_lock = threading.Lock()
_module: ModuleType | None = None
_ocr_module: ModuleType | None = None
# Keeps Windows DLL directory registrations and preloaded cores alive for the process.
_pins: list[object] = []


def native() -> ModuleType:
    """Returns the initialized extension, loading and starting the core on first call."""
    module = _module
    if module is not None:
        return module
    with _lock:
        if _module is None:
            _load()
        assert _module is not None
        return _module


def ocr_native() -> ModuleType:
    """Returns the OCR extension, loading the core first and then the OCR module beside it."""
    global _ocr_module
    native()  # the OCR module links the core, so the core loads and starts first
    if _ocr_module is not None:
        return _ocr_module
    with _lock:
        if _ocr_module is None:
            directory = native_dir()
            if directory is not None:
                _pin_library(directory / _library_name("jpdfium_ocr"), "the JPDFium OCR module")
            try:
                module = importlib.import_module("pyjpdfium._ocr_native")
            except ImportError as exc:
                raise NativeLoadError(f"the JPDFium OCR module is not available: {exc}") from exc
            library, compiled = module.api_version(), module.COMPILED_API_VERSION
            if library >> 16 != compiled >> 16 or (library & 0xFFFF) < (compiled & 0xFFFF):
                raise NativeLoadError("JPDFium OCR module API is incompatible with this build")
            if not module.struct_sizes_match():
                raise NativeLoadError("JPDFium OCR struct layouts differ from the compiled header")
            _ocr_module = module
        return _ocr_module


def native_dir() -> Path | None:
    configured = os.environ.get(NATIVE_DIR_ENV)
    if configured:
        return Path(configured)
    bundled = Path(__file__).with_name("_libs")
    return bundled if bundled.is_dir() else None


def _library_name(stem: str) -> str:
    if sys.platform == "win32":
        return f"{stem}.dll"
    if sys.platform == "darwin":
        return f"lib{stem}.dylib"
    return f"lib{stem}.so"


def _mapped_libraries() -> list[str]:
    maps = Path("/proc/self/maps")
    if not maps.exists():
        return []
    paths = set()
    for line in maps.read_text().splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) == 6 and parts[5].startswith("/"):
            paths.add(os.path.realpath(parts[5]))
    return sorted(paths)


def _check_soname_clash(directory: Path) -> None:
    """Refuses unstaged natives when another package already loaded a same-named library."""
    for soname in SHARED_SONAMES:
        if not (directory / soname).exists():
            continue  # staged, or not part of this build
        ours = os.path.realpath(directory / soname)
        mapped = [p for p in _mapped_libraries() if Path(p).name.startswith(soname)]
        # Ours mapped means it loaded first, so later dependencies still resolve to it.
        foreign = [p for p in mapped if p != ours]
        if foreign and ours not in mapped:
            raise NativeLoadError(
                f"{foreign[0]} is already loaded and shares the soname {soname} with "
                f"{directory}; stage the natives with tools/stage_natives.py"
            )


def _pin_library(path: Path, what: str) -> None:
    if not path.is_file():
        raise NativeLoadError(f"{what} not found at {path}; set {NATIVE_DIR_ENV} to staged natives")
    if sys.platform == "win32":
        _pins.append(os.add_dll_directory(str(path.parent)))
        return
    _check_soname_clash(path.parent)
    # Loading this file first binds the extension to it. RTLD_LOCAL keeps our PDFium's symbols
    # out of the global scope, where another PDFium in the process could resolve to them.
    _pins.append(ctypes.CDLL(str(path), mode=ctypes.RTLD_LOCAL))


def _pin_core(directory: Path) -> None:
    _pin_library(directory / _library_name("jpdfium"), "the JPDFium core")


def _loaded_core_paths() -> set[str]:
    return {p for p in _mapped_libraries() if Path(p).name.startswith("libjpdfium.so")}


def _check_identity(module: ModuleType) -> None:
    library = module.api_version()
    compiled = module.COMPILED_API_VERSION
    if library >> 16 != compiled >> 16 or (library & 0xFFFF) < (compiled & 0xFFFF):
        raise NativeLoadError(
            f"JPDFium core API {library >> 16}.{library & 0xFFFF} is incompatible with "
            f"this build of pyjpdfium ({compiled >> 16}.{compiled & 0xFFFF})"
        )
    if not module.struct_sizes_match():
        raise NativeLoadError("JPDFium core struct layouts differ from the compiled header")
    cores = _loaded_core_paths()
    if len(cores) > 1:
        # Two cores means two PDFium domains, each believing it is the only serializer.
        raise NativeLoadError(f"multiple JPDFium cores loaded: {sorted(cores)}")


def _renderer() -> Renderer:
    value = os.environ.get(RENDERER_ENV, "auto").strip().upper()
    try:
        return Renderer[value]
    except KeyError:
        raise NativeLoadError(f"{RENDERER_ENV} must be auto, agg or skia, not {value!r}") from None


def _load() -> None:
    global _module
    directory = native_dir()
    if directory is not None:
        _pin_core(directory)
    try:
        module = importlib.import_module("pyjpdfium._native")
    except ImportError as exc:
        raise NativeLoadError(f"could not load the JPDFium native core: {exc}") from exc
    _check_identity(module)
    module.runtime_init(int(_renderer()))
    _module = module
