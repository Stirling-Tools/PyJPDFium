"""Reads or grafts a text layer with tools independent of JPDFium, in its own process.

Usage: python -I text_layer_runner.py probe PDF [TERM ...]       # pypdfium2: text, boxes, render
       python -I text_layer_runner.py extract PDF [PDF ...]      # pypdfium2 and pdfminer.six text
       python -I text_layer_runner.py font PDF                   # qpdf check, fontTools font parse
       python -I text_layer_runner.py graft SOURCE_DIR REQUEST    # OCRmyPDF's own sandwich graft
Prints one JSON object. graft executes OCRmyPDF's _graft.py with the rest of OCRmyPDF stubbed.
"""

from __future__ import annotations

import enum
import hashlib
import importlib.util
import io
import json
import sys
import types
from pathlib import Path


def probe(path: str, terms: list[str]) -> dict:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    pdf = pdfium.PdfDocument(path)
    page = pdf[0]
    text = page.get_textpage()
    chars = []
    for i in range(text.count_chars()):
        left, bottom, right, top = text.get_charbox(i, loose=True)
        code = raw.FPDFText_GetUnicode(text.raw, i)
        generated = bool(raw.FPDFText_IsGenerated(text.raw, i))
        chars.append([chr(code), generated, left, bottom, right, top])
    hits = {}
    for term in terms:
        searcher = text.search(term)
        count = 0
        while searcher.get_next() is not None:
            count += 1
        hits[term] = count
    pixels = page.render(scale=100 / 72).to_pil().convert("L").tobytes()
    result = {
        "size": list(page.get_size()),
        "rotation": page.get_rotation(),
        "text": text.get_text_range(),
        "chars": chars,
        "search": hits,
        "blank": min(pixels) == 255,
        "render": hashlib.sha256(pixels).hexdigest(),
    }
    text.close()
    page.close()
    pdf.close()
    return result


def extract(paths: list[str]) -> list[dict]:
    """pypdfium2's text and character boxes, and pdfminer.six's text when it is installed."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        extract_text = None
    results = []
    for path in paths:
        pdf = pdfium.PdfDocument(path)
        page = pdf[0]
        text = page.get_textpage()
        chars, count, i = [], text.count_chars(), 0
        while i < count:
            code = raw.FPDFText_GetUnicode(text.raw, i)
            generated = bool(raw.FPDFText_IsGenerated(text.raw, i))
            left, bottom, right, top = text.get_charbox(i, loose=True)
            if 0xD800 <= code < 0xDC00 and i + 1 < count:  # PDFium indexes UTF-16 units
                low = raw.FPDFText_GetUnicode(text.raw, i + 1)
                code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                i += 1
            chars.append([chr(code), generated, left, bottom, right, top])
            i += 1
        results.append({
            "pdfium": text.get_text_range(),
            "chars": chars,
            "pdfminer": extract_text(path) if extract_text else None,
        })
        text.close()
        page.close()
        pdf.close()
    return results


def font(path: str) -> dict:
    import pikepdf
    from fontTools.ttLib import TTFont

    with pikepdf.Pdf.open(path) as pdf:
        problems = [str(p) for p in pdf.check_pdf_syntax()]
        type0 = pdf.pages[0].Resources.Font.F1
        data = type0.DescendantFonts[0].FontDescriptor.FontFile2.read_bytes()
    parsed = TTFont(io.BytesIO(data), checkChecksums=2)
    for tag in parsed.keys():
        parsed[tag]  # decompile every table, so a malformed one raises here
    order = parsed.getGlyphOrder()
    words = (int.from_bytes(data[i:i + 4].ljust(4, b"\0"), "big") for i in range(0, len(data), 4))
    return {
        "problems": problems,
        "tables": sorted(parsed.keys()),
        "contours": [parsed["glyf"][name].numberOfContours for name in order],
        "units_per_em": parsed["head"].unitsPerEm,
        "ascent": parsed["hhea"].ascent,
        "descent": parsed["hhea"].descent,
        "whole_font_checksum_ok": sum(words) & 0xFFFFFFFF == 0xB1B0AFBA,
    }


class ProcessingMode(str, enum.Enum):
    default = "default"
    force = "force"
    force_ocr_no_links = "force-ocr-no-links"
    skip = "skip"
    redo = "redo"
    strip_text = "strip"


def load_graft(source: Path):
    package = types.ModuleType("ocrmypdf")
    package.__path__ = []
    annots = types.ModuleType("ocrmypdf._annots")
    annots.link_annotations = lambda page: []
    annots.transfer_link_annotations = lambda *args, **kwargs: None
    jobcontext = types.ModuleType("ocrmypdf._jobcontext")
    jobcontext.PdfContext = object
    options = types.ModuleType("ocrmypdf._options")
    options.ProcessingMode = ProcessingMode
    pipeline = types.ModuleType("ocrmypdf._pipeline")
    pipeline.VECTOR_PAGE_DPI = 400
    sys.modules.update({"ocrmypdf": package, "ocrmypdf._annots": annots,
                        "ocrmypdf._jobcontext": jobcontext, "ocrmypdf._options": options,
                        "ocrmypdf._pipeline": pipeline})
    path = source / "ocrmypdf" / "_graft.py"
    spec = importlib.util.spec_from_file_location("ocrmypdf._graft", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module while it executes
    spec.loader.exec_module(module)
    return module


def graft(source: str, request: dict) -> dict:
    import pikepdf

    module = load_graft(Path(source))
    base = pikepdf.Pdf.open(request["base"], conversion_mode="explicit")
    # Only the attributes OcrGrafter.graft_page reads on the sandwich path.
    grafter = types.SimpleNamespace(
        pdf_base=base,
        path_base=Path(request["base"]).resolve(),
        context=types.SimpleNamespace(
            options=types.SimpleNamespace(mode=ProcessingMode(request.get("mode", "default")))
        ),
        pdfinfo=[types.SimpleNamespace(rotation=int(base.pages[0].obj.get("/Rotate", 0)))],
        use_sandwich_renderer=True,
        render_mode=module.RenderMode.UNDERNEATH,
        emplacements=1,
    )
    grafter._graft_sandwich_text_layer = types.MethodType(
        module.OcrGrafter._graft_sandwich_text_layer, grafter
    )
    module.OcrGrafter.graft_page(
        grafter,
        pageno=0,
        image=None,
        ocr_output=Path(request["text"]),
        ocr_tree=None,
        autorotate_correction=request.get("autorotate", 0),
    )
    base.save(request["output"])
    base.close()
    if request.get("stripped"):
        with pikepdf.Pdf.open(request["output"]) as pdf:
            module.strip_invisible_text(pdf, pdf.pages[0])
            pdf.save(request["stripped"])
    return {"grafted": True}


def main() -> None:
    command, args = sys.argv[1], sys.argv[2:]
    if command == "probe":
        result = probe(args[0], args[1:])
    elif command == "extract":
        result = extract(args)
    elif command == "font":
        result = font(args[0])
    elif command == "graft":
        result = graft(args[0], json.loads(args[1]))
    else:
        raise SystemExit(f"unknown command {command!r}")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
