"""Downloads OCRmyPDF's source (pinned, hash-checked) for the raster parity tests.

The wheel is unpacked, never installed: the tests execute only its pypdfium rasterizer and the
pure-Python Resolution class, against stubs for everything else.

  python tests/parity/fetch_reference.py [cache_dir]   # prints the source directory
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "17.13.0"
URL = (
    "https://files.pythonhosted.org/packages/3f/01/"
    "37f376f372901878e6166249bb2c15e943b1627294060be19d6f3ba3b849/"
    f"ocrmypdf-{VERSION}-py3-none-any.whl"
)
SHA256 = "f4d226f361c4b1498637f9c674daebfaf84223b84d9eba6bfba60a3ba260f9de"
NEEDED = ("ocrmypdf/builtin_plugins/pypdfium.py", "ocrmypdf/helpers.py")


def fetch(cache: Path) -> Path:
    source = cache / f"ocrmypdf-{VERSION}"
    if all((source / name).is_file() for name in NEEDED):
        return source
    cache.mkdir(parents=True, exist_ok=True)
    wheel = cache / URL.rsplit("/", 1)[1]
    with urllib.request.urlopen(URL, timeout=60) as response:  # noqa: S310 - pinned https URL
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise SystemExit(f"ocrmypdf wheel digest mismatch: {digest}")
    wheel.write_bytes(data)
    with zipfile.ZipFile(wheel) as archive:
        for name in NEEDED:
            archive.extract(name, source)
    return source


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".cache" / "pyjpdfium-parity"
    print(fetch(target))
