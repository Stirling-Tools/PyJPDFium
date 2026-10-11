"""OCRmyPDF plugin: JPDFium's rasterizer, PP-OCR engine and native text layer writer.

Load it explicitly; it is never picked up on its own:

    ocrmypdf --plugin pyjpdfium.ocrmypdf --output-type pdf in.pdf out.pdf

It replaces Tesseract, so Tesseract need not be installed, and refuses every mode it has not
been checked in rather than falling back. docs/OCRMYPDF.md lists what is supported.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import ocrmypdf
from ocrmypdf import hookimpl
from ocrmypdf.exceptions import BadArgsError, MissingDependencyError
from ocrmypdf.hocrtransform import BoundingBox, OcrClass, OcrElement
from ocrmypdf.pluginspec import OcrEngine, OrientationConfidence
from pydantic import BaseModel

import pyjpdfium

from .errors import InvalidArgumentError
from .profiles import PROFILE_ENV, verify_profile

if TYPE_CHECKING:
    from ocrmypdf._options import OcrOptions

log = logging.getLogger(__name__)

TESTED_OCRMYPDF = (17, 13)  # every 17.13.x; other releases are refused
ENGINE_NAME = "pyjpdfium"
# Only languages checked end to end are reported; the models read more, unqualified.
LANGUAGES = frozenset({"eng"})
_TESSERACT = "ocrmypdf.builtin_plugins.tesseract_ocr"
_TESSERACT_FIELDS = (
    "tesseract_config", "tesseract_pagesegmode", "tesseract_oem", "tesseract_thresholding",
    "tesseract_timeout", "tesseract_non_ocr_timeout", "tesseract_downsample_above",
    "tesseract_downsample_large_images", "user_words", "user_patterns",
)
# Preprocessing and orientation run outside the engine or need models this profile lacks.
_REFUSED_FLAGS = {
    "deskew": "--deskew needs a skew estimate, which this engine does not qualify",
    "rotate_pages": "--rotate-pages needs an orientation model, which this profile lacks",
    "clean": "--clean (unpaper) has not been checked with this engine",
    "clean_final": "--clean-final (unpaper) has not been checked with this engine",
    "remove_background": "--remove-background has not been checked with this engine",
}


class PyjpdfiumOptions(BaseModel):
    """Options under ``options.pyjpdfium``; on the command line, ``--pyjpdfium-*``."""

    profile: str | None = None
    threads: int = 1  # ONNX Runtime threads per page; OCRmyPDF already runs pages in parallel
    max_concurrent: int | None = None  # pages recognized at once per process; bounds memory


def ocrmypdf_version() -> tuple[int, ...]:
    return tuple(int(part) for part in ocrmypdf.__version__.split(".")[:3] if part.isdigit())


def check_compatible() -> None:
    if ocrmypdf_version()[:2] != TESTED_OCRMYPDF:
        raise MissingDependencyError(
            f"pyjpdfium.ocrmypdf supports OCRmyPDF {TESTED_OCRMYPDF[0]}.{TESTED_OCRMYPDF[1]}.x, "
            f"not {ocrmypdf.__version__}"
        )


def profile_dir(options: OcrOptions) -> Path | None:
    configured = options.pyjpdfium.profile or os.environ.get(PROFILE_ENV)
    return Path(configured) if configured else None


# --- Registration and preflight. These run in OCRmyPDF's main process, before workers start,
# so they never load native code: forked workers then start from a clean runtime.


@hookimpl
def initialize(plugin_manager):
    check_compatible()
    # This plugin is the OCR engine, so Tesseract's checks and options must not apply.
    plugin_manager.set_blocked(_TESSERACT)


@hookimpl
def register_options():
    from ocrmypdf.builtin_plugins.tesseract_ocr import TesseractOptions

    # OCRmyPDF's validation reads options.tesseract even when Tesseract is blocked.
    return {"pyjpdfium": PyjpdfiumOptions, "tesseract": TesseractOptions}


@hookimpl
def add_options(parser):
    group = parser.add_argument_group("PyJPDFium", "OCR with JPDFium's native PP-OCR engine")
    group.add_argument(
        "--pyjpdfium-profile", dest="pyjpdfium_profile", metavar="DIR",
        help=f"Fetched OCR model profile directory (default: ${PROFILE_ENV})",
    )
    group.add_argument(
        "--pyjpdfium-threads", dest="pyjpdfium_threads", type=int, default=1, metavar="N",
        help="ONNX Runtime threads per page (default 1; 0 lets ONNX Runtime choose)",
    )
    group.add_argument(
        "--pyjpdfium-max-concurrent", dest="pyjpdfium_max_concurrent", type=int, metavar="N",
        help="Most pages recognized at once in one process, to bound memory (default: --jobs)",
    )
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public lookup
        if "--ocr-engine" in action.option_strings and ENGINE_NAME not in action.choices:
            action.choices = [*action.choices, ENGINE_NAME]


@hookimpl
def check_options(options):
    if options.ocr_engine == "tesseract":
        raise BadArgsError("--ocr-engine tesseract cannot run with pyjpdfium.ocrmypdf loaded")
    if options.output_type not in ("pdf", "none"):
        raise BadArgsError(
            "pyjpdfium.ocrmypdf does not produce PDF/A; pass --output-type pdf "
            f"(got {options.output_type!r})"
        )
    for flag, reason in _REFUSED_FLAGS.items():
        if getattr(options, flag):
            raise BadArgsError(reason)
    if options.unpaper_args:
        raise BadArgsError("--unpaper-args has not been checked with this engine")
    defaults = type(options).model_fields
    changed = [f for f in _TESSERACT_FIELDS if getattr(options, f) != defaults[f].default]
    if changed:
        raise BadArgsError(f"Tesseract options do not apply to this engine: {', '.join(changed)}")
    if options.pyjpdfium.threads < 0:
        raise BadArgsError("--pyjpdfium-threads must not be negative")
    if options.pyjpdfium.max_concurrent is not None and options.pyjpdfium.max_concurrent < 1:
        raise BadArgsError("--pyjpdfium-max-concurrent must be at least 1")
    if options.ocr_engine == "none":
        return  # OCRmyPDF's null engine; only this plugin's rasterizer is used
    if options.pdf_renderer == "auto":
        # The native writer is the qualified renderer; fpdf2 stays available on request.
        options.pdf_renderer = "sandwich"
    directory = profile_dir(options)
    if directory is None:
        raise BadArgsError(f"pass --pyjpdfium-profile DIR or set {PROFILE_ENV}")
    try:
        log.debug("pyjpdfium OCR profile %s verified", verify_profile(directory).id)
    except InvalidArgumentError as exc:
        raise BadArgsError(str(exc)) from None


# --- Work in OCRmyPDF's workers, which may be threads or processes.


@hookimpl
def rasterize_pdf_page(
    input_file, output_file, raster_device, raster_dpi, pageno, page_dpi, rotation,
    filter_vector, stop_on_soft_error, options, use_cropbox,
):
    if options is not None and options.rasterizer != "auto":
        return None  # OCRmyPDF's own pypdfium or Ghostscript rasterizer was chosen explicitly
    # Only --rotate-pages previews ask for JPEG, and that option is refused above.
    pyjpdfium.rasterize_page(
        input_file,
        pageno - 1,
        output_file,
        device=str(raster_device),
        raster_dpi=(float(raster_dpi.x), float(raster_dpi.y)),
        output_dpi=(float(page_dpi.x), float(page_dpi.y)) if page_dpi else None,
        rotation=rotation or 0,
        use_cropbox=use_cropbox,
        filter_vector=filter_vector,
    )
    return output_file


@hookimpl
def filter_ocr_image(page, image):
    # Keeps Tesseract's size limits, still registered in workers, off this engine's input.
    return image


_engine_lock = threading.Lock()
_engine: tuple[int, tuple[str, int, int | None], pyjpdfium.OcrEngine] | None = None


def _get_engine(options: OcrOptions) -> pyjpdfium.OcrEngine:
    """One engine per process, shared by its threads; a forked child opens its own."""
    global _engine
    directory = profile_dir(options)
    if directory is None:
        raise BadArgsError(f"pass --pyjpdfium-profile DIR or set {PROFILE_ENV}")
    key = (os.fspath(directory), options.pyjpdfium.threads, options.pyjpdfium.max_concurrent)
    with _engine_lock:
        if _engine is None or _engine[0] != os.getpid() or _engine[1] != key:
            engine = pyjpdfium.OcrEngine(key[0], threads=key[1], max_concurrent=key[2])
            _engine = (os.getpid(), key, engine)
        return _engine[2]


def _recognize(input_file: Path, options: OcrOptions) -> pyjpdfium.OcrResult:
    # The exact image OCRmyPDF supplies, never a re-render of the source page.
    result = _get_engine(options).recognize(input_file)
    if not all(d > 0 for d in result.dpi):
        raise BadArgsError(f"{input_file} carries no resolution; OCRmyPDF always sets one")
    return result


def _sidecar(result: pyjpdfium.OcrResult) -> str:
    text = "\n".join(line.text for line in result.lines if line.text.strip())
    return text + "\n" if text else ""


class PyjpdfiumOcrEngine(OcrEngine):
    @staticmethod
    def version() -> str:
        return pyjpdfium.__version__

    @staticmethod
    def creator_tag(options) -> str:
        return f"PyJPDFium {pyjpdfium.__version__} PP-OCR"

    def __str__(self) -> str:
        return f"PyJPDFium PP-OCR {pyjpdfium.__version__}"

    @staticmethod
    def languages(options) -> frozenset[str]:
        return LANGUAGES

    @staticmethod
    def get_orientation(input_file, options) -> OrientationConfidence:
        raise BadArgsError(_REFUSED_FLAGS["rotate_pages"])

    @staticmethod
    def get_deskew(input_file, options) -> float:
        raise BadArgsError(_REFUSED_FLAGS["deskew"])

    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options) -> None:
        raise BadArgsError("pyjpdfium writes no hOCR; use --pdf-renderer sandwich or fpdf2")

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options) -> None:
        result = _recognize(Path(input_file), options)
        result.write_text_layer(output_pdf)
        Path(output_text).write_text(_sidecar(result), encoding="utf-8")

    @staticmethod
    def supports_generate_ocr() -> bool:
        return True

    @staticmethod
    def generate_ocr(input_file, options, page_number: int = 0):
        """The same recognition as an OcrElement tree, for OCRmyPDF's own fpdf2 renderer."""
        result = _recognize(Path(input_file), options)
        width, height = result.image_size
        page = OcrElement(
            ocr_class=OcrClass.PAGE,
            bbox=BoundingBox(left=0, top=0, right=width, bottom=height),
            dpi=float(result.dpi[0]),
            page_number=page_number,
        )
        for line in result.lines:
            if not line.text.strip():
                continue
            left, top, right, bottom = line.box
            box = BoundingBox(left=left, top=top, right=right, bottom=bottom)
            (x0, y0), (x1, y1) = line.polygon[0], line.polygon[1]
            # Counterclockwise from horizontal, as hOCR's textangle; image y runs down.
            angle = -math.degrees(math.atan2(y1 - y0, x1 - x0))
            # Word geometry is absent, so the line is one word; it is never split evenly.
            word = OcrElement(ocr_class=OcrClass.WORD, bbox=box, text=line.text,
                              confidence=line.confidence)
            page.children.append(OcrElement(
                ocr_class=OcrClass.LINE, bbox=box, poly=list(line.polygon),
                textangle=angle if abs(angle) >= 0.5 else None, children=[word],
            ))
        return page, _sidecar(result)


@hookimpl
def get_ocr_engine(options):
    if options is not None and options.ocr_engine not in ("auto", ENGINE_NAME):
        return None  # "none" selects OCRmyPDF's null engine
    return PyjpdfiumOcrEngine()
