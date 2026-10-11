# Compatibility

| Component | Requirement |
|---|---|
| Python | 3.10 or newer, CPython |
| JPDFium core | Safe API 1.x, minor at least the one PyJPDFium was built against |
| Platforms verified | linux-x64 (glibc) |
| Platforms pending | linux-arm64, macOS, Windows: the build supports them; no CI coverage yet |

On Windows the build also needs `jpdfium.lib`, the import library produced next to `jpdfium.dll`.

## Rasterization

`rasterize_page` follows OCRmyPDF 17.13's pypdfium rasterizer, with Ghostscript's behaviour where
the two disagree. It produces PNG only: `jpeg`, `jpeggray` and `tiff` devices are refused, and
`png256` is written as RGB. JPDFium's `docs/design/RASTER.md` lists every deviation and the
measured pixel parity.

## Text layers

`write_text_layer` writes the text-only PDF OCRmyPDF's `generate_pdf` hook returns, laid out as
OCRmyPDF 17.13's renderer lays out invisible text. OCRmyPDF's own sandwich graft accepts it, and
pypdfium2, qpdf and fontTools read it back (JPDFium's `docs/design/TEXT_LAYER.md`).

Right-to-left and mixed-direction words are laid out by the Unicode bidi algorithm, and a
`quad` on a `TextLine` or `TextWord` places rotated or skewed lines. Text is always passed in
logical order. Explicit bidi embeddings, overrides and isolates raise `UnsupportedError`.

### Multilingual qualification

`tests/parity/test_multilingual_parity.py` writes 23 samples, each flat, rotated 15, 90 and 180
degrees, and skewed. Every character box lands in its expected cell. Four extractors then read
the text, and each must reach at least the level below. The levels are, from strongest to
weakest:

- exact: the same text;
- NFC: equal after NFC normalization;
- words: the same words in another order;
- characters: the same characters, regrouped.

| Extractor | Left-to-right | Right-to-left | Mixed directions |
|---|---|---|---|
| PDFium (JPDFium's and pypdfium2's) | exact; words when upside down | NFC when horizontal; words when rotated | characters |
| pdfminer.six 20260107 | exact; characters at 90 degrees | exact; characters at 90 degrees | words; characters at 90 and 180 degrees |
| poppler 24.02 `pdftotext` | exact; characters at 15 degrees | exact; characters at 15 and 180 degrees | characters |

Most results beat their floor; flat right-to-left lines come back exact from all four. The
weaker results come from the extractors' own layout analysis:

- PDFium orders the words of upside-down lines, and of rotated right-to-left lines, by page
  position.
- PDFium can reorder Hebrew points, which NFC undoes.
- At a direction change, PDFium and poppler may drop or move a space. PDFium also swaps paired
  brackets in right-to-left text.
- pdfminer.six splits vertical text into single characters.
- poppler splits words on slanted baselines.

Search in viewers built on these extractors follows the same pattern.

## OCR

`OcrEngine` runs JPDFium's optional OCR module: PP-OCRv6 small on ONNX Runtime 1.30.0, with the
models of a profile directory fetched by JPDFium's `native/ocr/tools/fetch_profile.py`. On the
parity fixtures it reproduces the official `paddleocr` 3.7.0 pipeline exactly: the same polygons,
the same text, and confidences within 1.2e-7 (JPDFium's `docs/design/OCR.md`).

- Two profiles: `pp-ocrv6-small` and `pp-ocrv6-small-balanced`, each matching the reference
  pipeline at its own detection size ([PERFORMANCE.md](PERFORMANCE.md)).
- PNG input is read as OpenCV's `imread(IMREAD_COLOR)` reads it: alpha dropped, 16-bit samples
  cut to their high byte.
- Lines only: `OcrResult.word_geometry` is `"absent"`, and `text_lines()` keeps each line whole.
- No text-line orientation model, so vertical text is not read correctly, as in the reference
  configuration.
- The OCR extension is built only when the staged natives include `libjpdfium_ocr`.

## OCRmyPDF

`pyjpdfium.ocrmypdf` supports OCRmyPDF 17.13.x on Linux with staged natives, `--output-type pdf`
and English. [OCRMYPDF.md](OCRMYPDF.md) lists every refused option.

## Not in this release

- PDF/A output: rejected by design.
- Opening from bytes or file-like objects, saving or editing documents.
- Free-threaded CPython builds are untested.
