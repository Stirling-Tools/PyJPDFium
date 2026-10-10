# Compatibility

| Component | Requirement |
|---|---|
| Python | 3.10 or newer, CPython |
| JPDFium core | Safe API 1.x, minor at least the one PyJPDFium was built against |
| Platforms verified | linux-x64 (glibc) |
| Platforms pending | linux-arm64, macOS, Windows: the build supports them; no CI coverage yet |

On Windows the build also needs `jpdfium.lib`, the import library produced next to `jpdfium.dll`.

## Not in this release

- OCR, text-layer writing and the OCRmyPDF plugin.
- PDF/A output: rejected by design.
- Opening from bytes or file-like objects, saving or editing documents.
- Free-threaded CPython builds are untested.
