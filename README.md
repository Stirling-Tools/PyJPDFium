# PyJPDFium

Python bindings to [JPDFium](https://github.com/Stirling-Tools/JPDFium)'s native PDF core
(PDFium). No JVM required.

PyJPDFium is a thin [nanobind](https://github.com/wjakob/nanobind) binding over JPDFium's safe
`jpdf_*` C API. The native core, not Python or the GIL, owns PDFium serialization, object
lifetimes and handle validation, so the same rules hold for the Java and Python bindings.

Status: early development. This first pass covers documents, pages, rendering and transactional
PNG output.

```python
import pyjpdfium

with pyjpdfium.open_document("input.pdf") as document:
    with document.page(0) as page:
        page.render("page.png", dpi=(300, 300))   # atomic publish; failure leaves page.png as-is
        with page.render(dpi=150, pixel_format="gray") as bitmap:
            pixels = bitmap.view()                # zero-copy, read-only, shape (h, w)
```

## Behaviour

- `import pyjpdfium` loads no native library. The core loads and starts on first use.
- Objects are safe to share across threads. All PDFium work is serialized natively, and the GIL
  is released during native calls, so non-PDFium Python work keeps running.
- A closed object's handle can never be reused: use after close raises `StaleHandleError`.
- `close()` is idempotent. Closing a document with open pages raises `ResourceBusyError` and
  leaves the document usable.
- Bitmaps are independent of their page and document, and a `view()` keeps its pixels alive even
  after the bitmap is closed.
- One process uses one native core. JPDFium's Java binding is admitted by the same native
  domain, so the two can share a process only when both load the same `libjpdfium` file; the
  loader refuses a second copy.

## Building

PyJPDFium links a staged JPDFium native build; it never compiles its own copy of the core.

```bash
export JPDFIUM_NATIVE_DIR=/path/to/JPDFium/native/dist/linux-x64
export JPDFIUM_INCLUDE_DIR=/path/to/JPDFium/native/bridge/include
pip install --no-build-isolation .
PYJPDFIUM_NATIVE_DIR=$JPDFIUM_NATIVE_DIR pytest
```

`PYJPDFIUM_NATIVE_DIR` points the runtime at the staged natives. Wheels built with
`PYJPDFIUM_BUNDLE_NATIVES=ON` carry them in `pyjpdfium/_libs` instead.
`PYJPDFIUM_RENDERER` selects `auto` (default), `agg` or `skia`.

Native tests (`-m native`) need the real core and are skipped when the extension is not built.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.
