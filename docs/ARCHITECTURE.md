# Architecture

PyJPDFium is a peer of JPDFium's Java binding. Both bind one safe native C API,
`jpdfium_api.h`, implemented once in JPDFium's `libjpdfium` core. The core, not Python, owns:

- PDFium serialization: one native domain per process; the GIL is never the lock.
- Object lifetime: generation-checked handles, parent retention, `BUSY` instead of partial close.
- Output safety: staged, bounded, atomically published files.

JPDFium's Java binding reaches PDFium through generated `jpdf_guard_*` shims admitted by the same
domain, so both bindings can run in one process without a second serializer, provided they load
the same `libjpdfium` file.

The full contracts live in JPDFium's `docs/design/` (`ARCHITECTURE.md`, `NATIVE_ABI.md`,
`LIFETIME.md`, `CALLBACKS.md`, `CAPABILITIES.md`).

## Layers

```text
pyjpdfium            pure Python API: Document, Page, Bitmap, runtime_*
pyjpdfium._loader    lazy load, core pinning, identity checks, runtime init
pyjpdfium._native    nanobind module: one function per jpdf_* call, GIL released around it
libjpdfium           the shared native core (never compiled into the extension)
```

`import pyjpdfium` and its pure modules load nothing native. The first call that needs the core
runs `_loader.native()`, which:

1. Loads the core from `PYJPDFIUM_NATIVE_DIR` or the bundled `pyjpdfium/_libs`, by exact path, so
   the extension binds to that copy.
2. Checks the core's API version and struct layouts against the compiled header, and refuses to
   continue if more than one `libjpdfium` is mapped into the process.
3. Calls `jpdf_runtime_init` (explicit lazy initialization).

## Errors

Native status codes map one-to-one onto the classes in `pyjpdfium.errors`. Unknown codes become
`InternalError`, never success. Errors carry `status` and `status_name`, and their message is the
native detail captured on the failing thread before the GIL is reacquired.

## Lifetime in Python

`close()` is idempotent and thread-safe. Context managers close on exit. Objects that are never
closed are reclaimed by `weakref.finalize`; because a page holds its document, a page is always
finalized before its document. Native code never cascades a close, and Python never forces one.

`Bitmap.view()` returns a read-only memoryview whose owner holds a native view. The view pins the
pixels, so it stays valid after the bitmap, page or document is closed.

## Isolation

The native core runs in-process. It removes the JVM, not the crash domain: a native fault ends the
interpreter. Untrusted or hard-budget jobs should run in a worker process.
