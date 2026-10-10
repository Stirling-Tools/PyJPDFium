from types import SimpleNamespace

import pytest

from pyjpdfium import _loader
from pyjpdfium.errors import NativeLoadError
from pyjpdfium.models import Renderer


def fake_module(library=0x10000, compiled=0x10000, layouts=True):
    return SimpleNamespace(
        api_version=lambda: library,
        COMPILED_API_VERSION=compiled,
        struct_sizes_match=lambda: layouts,
    )


@pytest.fixture(autouse=True)
def single_core(monkeypatch):
    monkeypatch.setattr(_loader, "_loaded_core_paths", lambda: {"/lib/libjpdfium.so"})


def test_compatible_core_is_accepted():
    _loader._check_identity(fake_module(library=0x10003, compiled=0x10001))


@pytest.mark.parametrize(
    ("library", "compiled"),
    [(0x20000, 0x10000), (0x10000, 0x10002)],
    ids=["major-mismatch", "older-minor"],
)
def test_incompatible_api_is_rejected(library, compiled):
    with pytest.raises(NativeLoadError, match="incompatible"):
        _loader._check_identity(fake_module(library=library, compiled=compiled))


def test_layout_mismatch_is_rejected():
    with pytest.raises(NativeLoadError, match="layouts"):
        _loader._check_identity(fake_module(layouts=False))


def test_two_cores_are_rejected(monkeypatch):
    monkeypatch.setattr(
        _loader, "_loaded_core_paths", lambda: {"/a/libjpdfium.so", "/b/libjpdfium.so"}
    )
    with pytest.raises(NativeLoadError, match="multiple JPDFium cores"):
        _loader._check_identity(fake_module())


def test_renderer_selection(monkeypatch):
    monkeypatch.setenv(_loader.RENDERER_ENV, "agg")
    assert _loader._renderer() is Renderer.AGG
    monkeypatch.setenv(_loader.RENDERER_ENV, "vulkan")
    with pytest.raises(NativeLoadError, match="PYJPDFIUM_RENDERER"):
        _loader._renderer()


def test_missing_core_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv(_loader.NATIVE_DIR_ENV, str(tmp_path))
    with pytest.raises(NativeLoadError, match="not found"):
        _loader._pin_core(_loader.native_dir())
