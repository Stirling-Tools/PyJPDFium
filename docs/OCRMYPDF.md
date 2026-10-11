# OCRmyPDF plugin

`pyjpdfium.ocrmypdf` runs OCRmyPDF 17.13 with JPDFium's native rasterizer, its PP-OCR engine
and its invisible text layer writer. Tesseract and Ghostscript are not needed.

```bash
pip install "pyjpdfium[ocrmypdf]"
export PYJPDFIUM_OCR_PROFILE=/path/to/pp-ocrv6-small-balanced   # see fetch_profile.py
ocrmypdf --plugin pyjpdfium.ocrmypdf --output-type pdf input.pdf output.pdf
```

The plugin is loaded only by `--plugin`; installing PyJPDFium never changes how OCRmyPDF runs
without it.

## What it does

- Rasterization: with `--rasterizer auto`, pages are rasterized by `rasterize_page`, which matches
  OCRmyPDF's own pypdfium rasterizer (JPDFium `docs/design/RASTER.md`). `--rasterizer pypdfium`
  or `ghostscript` hands rasterization back to OCRmyPDF.
- Engine: the plugin is the OCR engine for `--ocr-engine auto` and for `--ocr-engine pyjpdfium`,
  a value it registers. `--ocr-engine none` keeps OCRmyPDF's null engine.
- Text: with `--pdf-renderer auto` or `sandwich`, `generate_pdf` recognizes the image and writes
  the text layer natively. `--pdf-renderer fpdf2` passes the same lines to OCRmyPDF's own
  renderer through `generate_ocr`, as a reference.
- Exact image: the engine reads only the image OCRmyPDF hands it, after every filter, never the
  source page. A test plugin that blanks part of the OCR image proves the hidden text is not
  found while the visible page keeps it.
- Engines load once per worker process and are shared by its threads. ONNX Runtime uses one
  thread per page by default (`--pyjpdfium-threads`), since OCRmyPDF already runs pages in
  parallel. `--pyjpdfium-max-concurrent N` caps the pages recognized at once in a process, to
  bound memory.

Speed, memory and accuracy against Tesseract, per profile, are in
[PERFORMANCE.md](PERFORMANCE.md). The balanced profile is the one to use for ordinary
documents.

The plugin blocks OCRmyPDF's built-in Tesseract plugin, so Tesseract's checks and options do not
apply. OCRmyPDF's own validation still reads `options.tesseract`, so the plugin registers that
option model with its defaults.

## Refused

Anything not yet checked end to end is refused before any page is processed:

| Request | Why |
|---|---|
| `--output-type` other than `pdf` or `none` (the default `auto` included) | PDF/A output is not produced |
| `--deskew`, `--rotate-pages` | The profile has no skew or orientation model |
| `--clean`, `--clean-final`, `--unpaper-args`, `--remove-background` | Not checked with this engine |
| `--ocr-engine tesseract`, any Tesseract option | Tesseract is not the engine |
| `-l` other than `eng` | Only checked languages are reported; the models read more |
| An unfetched or modified profile | Every file must match its pinned digest |
| An OCRmyPDF release other than 17.13.x | The plugin API is checked against that release only |

## Sharing a process with pypdfium2

OCRmyPDF imports pypdfium2, whose `libpdfium.so` has the same soname as JPDFium's PDFium.
`tools/stage_natives.py` stages JPDFium's natives with their own sonames
(`libjpdfium_pdfium.so`, `libjpdfium_onnxruntime.so.1`), and the loader loads the core with
`RTLD_LOCAL`, so neither PDFium's symbols reach the other. Unstaged natives are refused with an
explicit error when a same-named library is already loaded.

```bash
python tools/stage_natives.py /path/to/JPDFium/native/dist/linux-x64 natives
export PYJPDFIUM_NATIVE_DIR=$PWD/natives
```

## Evidence

`tests/ocrmypdf` runs OCRmyPDF's real command line, installed from hash-pinned wheels into its
own environment, with no network and neither Tesseract nor Ghostscript installed:

- a scanned page gains exactly its text, renders identically, and gets its `--sidecar` text;
- a `/Rotate 90` page reads upright;
- on a page that already has text, the default mode refuses it, `--skip-text` leaves it
  untouched, and `--force-ocr` rasterizes and reads it;
- `--redo-ocr` replaces an earlier layer without doubling it;
- the exact-image check above, and the fpdf2 reference renderer reading the same words;
- every refusal in the table, and a tampered profile.
