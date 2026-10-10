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

## Not in this release

- OCR, text-layer writing and the OCRmyPDF plugin.
- PDF/A output: rejected by design.
- Opening from bytes or file-like objects, saving or editing documents.
- Free-threaded CPython builds are untested.
