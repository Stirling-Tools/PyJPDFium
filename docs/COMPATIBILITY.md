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
pypdfium2, qpdf and fontTools read it back (JPDFium's `docs/design/TEXT_LAYER.md`). Right-to-left
scripts raise `UnsupportedError` until the multilingual writer lands.

## OCR

`OcrEngine` runs JPDFium's optional OCR module: PP-OCRv6 small on ONNX Runtime 1.30.0, with the
models of a profile directory fetched by JPDFium's `native/ocr/tools/fetch_profile.py`. On the
parity fixtures it reproduces the official `paddleocr` 3.7.0 pipeline exactly: the same polygons,
the same text, and confidences within 1.2e-7 (JPDFium's `docs/design/OCR.md`).

- PNG input is read as OpenCV's `imread(IMREAD_COLOR)` reads it: alpha dropped, 16-bit samples
  cut to their high byte.
- Lines only: `OcrResult.word_geometry` is `"absent"`, and `text_lines()` keeps each line whole.
- No text-line orientation model, so vertical text is not read correctly, as in the reference
  configuration.
- The OCR extension is built only when the staged natives include `libjpdfium_ocr`.

## Not in this release

- The OCRmyPDF plugin.
- PDF/A output: rejected by design.
- Opening from bytes or file-like objects, saving or editing documents.
- Free-threaded CPython builds are untested.
