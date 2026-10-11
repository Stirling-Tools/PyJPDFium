"""The ``pyjpdfium`` command: runtime identity, page rendering, OCR, profiles and a doctor.

Exit status is 0 on success, 1 when a command fails or ``doctor`` finds a problem, and 2 for
usage errors.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .errors import PyJPDFiumError

CORE_CAPABILITIES = (
    "runtime.lifecycle", "pdf.open", "pdf.render", "pdf.text", "pdf.raster", "image.load",
    "image.png_write", "image.rectify", "output.transaction", "legacy.guards",
    "text_layer.write", "text_layer.bidi", "text_layer.quad",
    "fonts.shape_explicit", "fonts.subset", "pdf.optimize", "svg.render",
)
OCR_CAPABILITIES = ("ocr.recognize", "ocr.word_geometry")
TEXT_LAYER_FONTS = (
    ("glyphless", "built in", "invisible text in any script and direction; draws nothing"),
)


def _out(line: str = "") -> None:
    print(line, flush=True)


def cmd_info(args: argparse.Namespace) -> int:
    from . import capability, open_document, runtime_info

    info = runtime_info()
    if args.pdf is None:
        _out(f"pyjpdfium {__version__}")
        _out(f"api {info.api_version[0]}.{info.api_version[1]}  build {info.build_id}")
        _out(f"renderer {info.renderer.name.lower() if info.renderer else 'auto'}")
        for name in CORE_CAPABILITIES:
            _out(f"  {name:22s} {capability(name).name.lower()}")
        return 0
    with open_document(args.pdf, password=args.password) as document:
        _out(f"{args.pdf}: {document.page_count} pages")
        for index in range(document.page_count):
            with document.page(index) as page:
                size = page.size
                _out(f"  page {index + 1}: {size.width:.2f} x {size.height:.2f} pt")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    from . import rasterize_page

    result = rasterize_page(args.pdf, args.page - 1, args.output, device=args.device,
                            raster_dpi=args.dpi, password=args.password)
    _out(f"{args.output}: {result.width} x {result.height} px")
    return 0


def _profile(args: argparse.Namespace) -> Path:
    from .profiles import PROFILE_ENV, default_profile_dir

    directory = Path(args.profile) if args.profile else default_profile_dir()
    if directory is None:
        raise SystemExit(f"pyjpdfium: pass --profile DIR or set {PROFILE_ENV}")
    return directory


def cmd_ocr(args: argparse.Namespace) -> int:
    from . import OcrEngine, rasterize_page, write_text_layer

    source = Path(args.input)
    with tempfile.TemporaryDirectory(prefix="pyjpdfium-ocr-") as work:
        image = source
        if source.suffix.lower() == ".pdf":
            image = Path(work) / "page.png"
            rasterize_page(source, args.page - 1, image, device="png16m", raster_dpi=args.dpi)
        with OcrEngine(_profile(args), threads=args.threads) as engine:
            result = engine.recognize(image)
    if args.layer:
        write_text_layer(args.layer, result.text_lines(), image_size=result.image_size,
                         dpi=result.dpi)
    if args.json:
        lines = [{"text": line.text, "polygon": line.polygon, "confidence": line.confidence}
                 for line in result.lines]
        _out(json.dumps({"image_size": result.image_size, "dpi": result.dpi,
                         "profile": result.profile, "lines": lines}, ensure_ascii=False))
    else:
        _out(result.text)
    return 0


def cmd_fonts(args: argparse.Namespace) -> int:
    for name, source, description in TEXT_LAYER_FONTS:
        _out(f"{name:10s} {source:9s} {description}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from .profiles import default_profile_dir, verify_profile

    directories = [Path(d) for d in args.dirs] or [d for d in [default_profile_dir()] if d]
    if not directories:
        _out("no profile given and PYJPDFIUM_OCR_PROFILE is not set")
        return 1
    failed = False
    for directory in directories:
        try:
            profile = verify_profile(directory)
        except PyJPDFiumError as exc:
            _out(f"FAIL {directory}: {exc}")
            failed = True
            continue
        _out(f"ok   {profile.id} at {directory}")
        for item in profile.files:
            _out(f"       {item.role:18s} {item.name:16s} sha256 {item.sha256[:16]}")
    return 1 if failed else 0


class _Report:
    def __init__(self) -> None:
        self.problems = 0

    def ok(self, what: str, detail: str = "") -> None:
        _out(f"ok       {what}{': ' + detail if detail else ''}")

    def note(self, what: str, detail: str) -> None:
        _out(f"note     {what}: {detail}")

    def problem(self, what: str, detail: str) -> None:
        self.problems += 1
        _out(f"PROBLEM  {what}: {detail}")


def _loaded_libraries() -> list[str]:
    from ._loader import _mapped_libraries

    names = ("libjpdfium", "libpdfium", "libonnxruntime")
    return [p for p in _mapped_libraries() if Path(p).name.startswith(names)]


def cmd_doctor(args: argparse.Namespace) -> int:
    """Reports identity, capabilities, profiles and dependencies; recognizes no document."""
    from . import _loader
    from .profiles import default_profile_dir, sha256_file, verify_profile

    report = _Report()
    report.ok("pyjpdfium", f"{__version__} on Python {platform.python_version()} "
                           f"({platform.system()} {platform.machine()})")
    directory = _loader.native_dir()
    report.ok("natives", str(directory) if directory else "found through the loader path")
    try:
        from . import capability, runtime_info

        info = runtime_info()
    except PyJPDFiumError as exc:
        report.problem("core", str(exc))
        return 1
    report.ok("core", f"api {info.api_version[0]}.{info.api_version[1]}, build {info.build_id}, "
                      f"renderer {info.renderer.name.lower() if info.renderer else 'auto'}")
    for name in CORE_CAPABILITIES:
        report.ok(f"capability {name}", capability(name).name.lower())
    try:
        ocr = _loader.ocr_native()
    except PyJPDFiumError as exc:
        report.note("ocr module", f"not available ({exc})")
        ocr = None
    if ocr is not None:
        version = ocr.api_version()
        report.ok("ocr module", f"api {version >> 16}.{version & 0xFFFF}")
        for name in OCR_CAPABILITIES:
            level = {0: "absent", 1: "implemented", 2: "qualified"}.get(ocr.capability(name), "?")
            report.ok(f"capability {name}", level)
    # Listed once both modules are in, so the identities cover everything that loaded.
    for path in _loaded_libraries():
        report.ok("loaded", f"{path} sha256 {sha256_file(Path(path))[:16]}")
    profile_dir = Path(args.profile) if args.profile else default_profile_dir()
    if profile_dir is None:
        report.note("ocr profile", "none given; pass --profile or set PYJPDFIUM_OCR_PROFILE")
    else:
        try:
            profile = verify_profile(profile_dir)
        except PyJPDFiumError as exc:
            report.problem("ocr profile", str(exc))
        else:
            report.ok("ocr profile", f"{profile.id} at {profile_dir}, every digest matches")
    for name, source, _ in TEXT_LAYER_FONTS:
        report.ok(f"font {name}", source)
    try:
        plugin = importlib.import_module("pyjpdfium.ocrmypdf")
        plugin.check_compatible()
    except ImportError as exc:
        report.note("ocrmypdf", f"not installed; the plugin is optional ({exc.name})")
    except Exception as exc:  # noqa: BLE001 - OCRmyPDF's own exception types
        report.problem("ocrmypdf", str(exc))
    else:
        import ocrmypdf

        report.ok("ocrmypdf", f"{ocrmypdf.__version__}, supported by pyjpdfium.ocrmypdf")
    for tool in ("tesseract", "gs"):
        found = shutil.which(tool)
        report.note(tool, f"{'found' if found else 'not found'}; not needed by pyjpdfium")
    _out(f"{report.problems} problem(s)")
    return 1 if report.problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyjpdfium", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"pyjpdfium {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="runtime identity and capabilities, or a PDF's pages")
    info.add_argument("pdf", nargs="?")
    info.add_argument("--password")
    info.set_defaults(run=cmd_info)

    render = sub.add_parser("render", help="rasterize one page to PNG")
    render.add_argument("pdf")
    render.add_argument("output")
    render.add_argument("--page", type=int, default=1, help="1-based (default 1)")
    render.add_argument("--dpi", type=float, default=300.0)
    render.add_argument("--device", default="png16m",
                        choices=["png16m", "pnggray", "pngmono", "pngmonod", "png256"])
    render.add_argument("--password")
    render.set_defaults(run=cmd_render)

    ocr = sub.add_parser("ocr", help="recognize a PNG, or one page of a PDF")
    ocr.add_argument("input")
    ocr.add_argument("--page", type=int, default=1, help="1-based, for PDF input (default 1)")
    ocr.add_argument("--dpi", type=float, default=300.0, help="raster DPI for PDF input")
    ocr.add_argument("--profile", help="profile directory (default $PYJPDFIUM_OCR_PROFILE)")
    ocr.add_argument("--threads", type=int, default=0, help="ONNX Runtime threads (0: auto)")
    ocr.add_argument("--layer", metavar="PDF", help="also write an invisible text layer")
    ocr.add_argument("--json", action="store_true", help="lines with polygons and confidences")
    ocr.set_defaults(run=cmd_ocr)

    fonts = sub.add_parser("fonts", help="fonts available to text layers")
    fonts.set_defaults(run=cmd_fonts)

    models = sub.add_parser("models", help="verify OCR profile directories against their digests")
    models.add_argument("dirs", nargs="*", metavar="DIR")
    models.set_defaults(run=cmd_models)

    doctor = sub.add_parser("doctor", help="check this installation without recognizing anything")
    doctor.add_argument("--profile", help="profile directory (default $PYJPDFIUM_OCR_PROFILE)")
    doctor.set_defaults(run=cmd_doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except PyJPDFiumError as exc:
        print(f"pyjpdfium {args.command}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
