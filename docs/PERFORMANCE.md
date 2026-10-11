# Performance

Measured with `tools/bench_ocrmypdf.py`. Each run is OCRmyPDF 17.13's real command line, offline,
on a 16-core x86-64 Linux container. The corpus is 12 scanned pages at 300 dpi, made from seeded
English text in Helvetica, Times and Courier at 11 to 13 pt, so the ground truth is exact.

- Accuracy is the character error rate (CER) of the text PDFium extracts from the output.
- Memory is the peak resident size of the largest process.
- Tesseract is 5.3.4 from Ubuntu 24.04 with OCRmyPDF's defaults.

## OCRmyPDF, one page at a time (`--jobs 1`)

| Engine | Seconds per page | CPU seconds | Peak memory | CER |
|---|---|---|---|---|
| Tesseract | 1.20 | 14.2 | 127 MiB | 0.0001 |
| pyjpdfium, `pp-ocrv6-small` | 5.44 | 65.2 | 3427 MiB | 0.0002 |
| pyjpdfium, `pp-ocrv6-small-balanced` | 3.39 | 40.6 | 1342 MiB | 0.0001 |

## OCRmyPDF, eight pages at once (`--jobs 8`)

| Engine | Seconds per page | CPU seconds | Peak memory | CER |
|---|---|---|---|---|
| Tesseract | 0.37 | 15.8 | 176 MiB | 0.0001 |
| pyjpdfium, `pp-ocrv6-small` | 2.29 | 155.9 | 14710 MiB | 0.0002 |
| pyjpdfium, balanced | 1.22 | 79.0 | 3561 MiB | 0.0001 |
| pyjpdfium, balanced, `--pyjpdfium-max-concurrent 4` | 1.33 | 51.9 | 3118 MiB | 0.0001 |
| pyjpdfium, balanced, `--pyjpdfium-max-concurrent 2` | 1.89 | 43.7 | 2301 MiB | 0.0001 |

## What the numbers say

- On clean 300 dpi scans of English, Tesseract is faster and smaller at the same accuracy. The
  plugin's case is OCR without Tesseract or Ghostscript, and the PP-OCR models.
- Detection size dominates memory. `pp-ocrv6-small` detects at the page's full resolution
  (about 2560 x 3328 pixels here), which is PaddleOCR's default. `pp-ocrv6-small-balanced` caps
  the longer side at 1600 pixels. It is 1.6 times faster alone and 1.9 times faster at eight
  jobs, uses 2.6 and 4.1 times less memory, and loses no accuracy on this corpus. Both profiles
  match the official PaddleOCR pipeline exactly at their own settings
  (`tests/parity/test_ocr_parity.py`).
- With the balanced profile, recognition now takes most of each page: about 2.2 of 3.4
  seconds for 34 long lines. Its inputs are fixed by the reference pipeline.
- Each page being recognized holds its own model activations. `--pyjpdfium-max-concurrent`
  (or `OcrEngine(max_concurrent=...)`) caps how many run at once in one process, trading wall
  time for memory. It also cuts CPU time, since eight concurrent runs compete for memory
  bandwidth.
- Opening an engine, which reads and checks the 31 MB of models, takes 0.2 seconds. The plugin
  opens one per worker process and shares it across that process's threads.

## Recommendations

- Use `pp-ocrv6-small-balanced` for ordinary documents. Keep `pp-ocrv6-small` for small text,
  where full-resolution detection can find what the capped size misses.
- On machines with less than about 0.5 GB per OCRmyPDF job, set `--pyjpdfium-max-concurrent`.
- Outside OCRmyPDF, `OcrEngine(threads=0)` lets ONNX Runtime use every core for one page: 1.08
  seconds per page with the balanced profile and four threads, against 2.67 with one.
