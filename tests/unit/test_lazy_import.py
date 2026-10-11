import subprocess
import sys

PROBE = """
import sys
import pyjpdfium
import pyjpdfium.errors, pyjpdfium.models, pyjpdfium.pdf, pyjpdfium.runtime
import pyjpdfium.raster, pyjpdfium.textlayer
assert pyjpdfium.PixelFormat.RGB == 2
loaded = [m for m in sys.modules if m.startswith("pyjpdfium._native")]
assert not loaded, loaded
try:
    maps = open("/proc/self/maps").read()
except OSError:
    maps = ""
assert "libjpdfium" not in maps and "libpdfium" not in maps
print("lazy-ok")
"""


def test_import_loads_no_native_code():
    # A fresh interpreter, so nothing another test loaded can hide an eager import.
    result = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "lazy-ok" in result.stdout


def test_unknown_attribute_raises():
    import pyjpdfium

    try:
        pyjpdfium.does_not_exist  # noqa: B018
    except AttributeError as exc:
        assert "does_not_exist" in str(exc)
    else:
        raise AssertionError("expected AttributeError")


def test_every_export_resolves():
    import pyjpdfium

    for name in pyjpdfium.__all__:
        assert getattr(pyjpdfium, name) is not None
