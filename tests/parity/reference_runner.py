"""Runs OCRmyPDF's pypdfium rasterize_pdf_page in its own process and reports the PNG it wrote.

Usage: python -I reference_runner.py SOURCE_DIR REQUEST_JSON
Only pypdfium.py and the Resolution class from helpers.py execute; the rest of OCRmyPDF is stubbed.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path


def resolution_class(helpers: Path) -> type:
    tree = ast.parse(helpers.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Resolution")
    header = (
        "from __future__ import annotations\n"
        "from collections.abc import Iterable\n"
        "from math import isclose, isfinite\n"
        "from statistics import harmonic_mean\n"
        "from typing import Any, Callable, Generic, TypeVar\n"
        "T = TypeVar('T', float, int)\n"
    )
    namespace: dict = {}
    exec(compile(header + ast.unparse(node), str(helpers), "exec"), namespace)  # noqa: S102
    return namespace["Resolution"]


def load_reference(source: Path):
    resolution = resolution_class(source / "ocrmypdf" / "helpers.py")
    package = types.ModuleType("ocrmypdf")
    package.hookimpl = lambda func: func
    exceptions = types.ModuleType("ocrmypdf.exceptions")
    exceptions.MissingDependencyError = type("MissingDependencyError", (Exception,), {})
    helpers = types.ModuleType("ocrmypdf.helpers")
    helpers.Resolution = resolution
    sys.modules.update({"ocrmypdf": package, "ocrmypdf.exceptions": exceptions,
                        "ocrmypdf.helpers": helpers})
    path = source / "ocrmypdf" / "builtin_plugins" / "pypdfium.py"
    spec = importlib.util.spec_from_file_location("ocrmypdf.builtin_plugins.pypdfium", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, resolution


def main() -> None:
    source, request = Path(sys.argv[1]), json.loads(sys.argv[2])
    module, resolution = load_reference(source)
    page_dpi = request.get("page_dpi")
    module.rasterize_pdf_page(
        input_file=Path(request["input"]),
        output_file=Path(request["output"]),
        raster_device=request["device"],
        raster_dpi=resolution(*request["raster_dpi"]),
        pageno=request["pageno"],
        page_dpi=resolution(*page_dpi) if page_dpi else None,
        rotation=request.get("rotation", 0),
        filter_vector=False,
        stop_on_soft_error=True,
        options=None,
        use_cropbox=request.get("use_cropbox", False),
    )
    from PIL import Image

    with Image.open(request["output"]) as image:
        print(json.dumps({"size": image.size, "mode": image.mode, "dpi": image.info.get("dpi")}))


if __name__ == "__main__":
    main()
