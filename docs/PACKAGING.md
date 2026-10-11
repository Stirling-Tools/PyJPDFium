# Packaging

`tools/build_wheel.py` builds a self-contained Linux wheel from a JPDFium checkout:

```bash
python tools/build_wheel.py /path/to/JPDFium dist/
```

1. JPDFium's own `native/bundle-runtime-deps.sh` collects the core's runtime closure and runs the
   same checks as its Java natives jar: no executable stacks, hermetic dependencies, exported
   symbols, no orphans, lean layout, and the size budget. The optional OCR module joins from
   `native/dist/ocr-<platform>` afterwards, as it is not part of the core bundle.
2. `tools/stage_natives.py` gives JPDFium's PDFium and ONNX Runtime their own sonames and sets
   every RUNPATH to `$ORIGIN`, so the wheel can share a process with pypdfium2 or onnxruntime
   wheels ([OCRMYPDF.md](OCRMYPDF.md)).
3. License texts go to `pyjpdfium/_libs/licenses`: JPDFium's notice and licenses, ONNX
   Runtime's license and third-party notices, and the Debian copyright file of every system
   library the bundler copied in.
4. `pyjpdfium/_libs/identity.json` records:
   - PyJPDFium's and JPDFium's revisions, and the safe and OCR ABI versions;
   - the PDFium pin and ONNX Runtime version, and every capability's level;
   - the model profiles the module supports, with their digests;
   - the bundled system libraries, the license inventory, and every file's digest before and
     after staging.
5. The wheel is tagged `manylinux_2_<n>` for the newest glibc symbol any bundled file needs.

`pyjpdfium doctor` checks an installation against `natives-manifest.json`, file by file, and
reports any PDFium, ONNX Runtime or JPDFium library loaded from outside the wheel.

## Size

The wheel built on Ubuntu 24.04 is 26.1 MiB (`manylinux_2_38_x86_64`). The largest parts are
ONNX Runtime (29 MB unpacked), JPDFium's core (7 MB) and PDFium (6 MB). Model profiles are not
in the wheel; they are fetched and pinned separately (JPDFium `docs/design/OCR.md`).

JPDFium's release builds rebuild qpdf with native crypto and HarfBuzz without GLib. Those
scripts fetch upstream's newest release without a pinned version or digest, so this build does
not run them. It bundles Ubuntu's qpdf and HarfBuzz instead, which bring GnuTLS, Nettle, GMP,
GLib and their dependencies. These are LGPL libraries, shipped as replaceable shared libraries
with their copyright files. A build without Ghostscript still has some LGPL components.

## Clean machine

`tests/clean_machine/check.py` runs on a fresh `ubuntu:24.04` container with only `python3`
and `python3-venv` added, no network, and no `PYJPDFIUM_NATIVE_DIR`. It installs the wheel
offline and checks the following:

- `pyjpdfium doctor` reports no problems, and all 38 bundled files match their digests;
- a page renders, its text reads back, OCR recognizes it, and a text layer is written;
- OCRmyPDF, installed offline from `tests/ocrmypdf/requirements.txt`, OCRs a scanned page with
  the plugin.

Every native library the process loads comes from the wheel, except the C runtime and the five
that Python's own standard library loads: zlib, bzip2, libffi, liblzma and expat. The bundled
zlib then resolves to the already-loaded system copy, which has the same ABI.

## OCRmyPDF dependencies

`tests/clean_machine/prune.sh` installs OCRmyPDF's pinned dependencies with some left out:

| Dependency | With the plugin |
|---|---|
| Tesseract, Ghostscript | Not installed; never needed |
| pypdfium2 | Imported by OCRmyPDF when installed, but never called: its rasterizer logs nothing. Works when not installed |
| fpdf2, uharfbuzz | Needed only for `--pdf-renderer fpdf2`. Work when not installed |
| img2pdf | Required: OCRmyPDF imports it at startup |

OCRmyPDF's package metadata still requires pypdfium2, fpdf2 and uharfbuzz. Leaving them out
needs an install with `--no-deps` from a pinned list, as the script does.
