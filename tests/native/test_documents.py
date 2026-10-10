import gc

import pytest

import pyjpdfium
from pyjpdfium import errors

pytestmark = pytest.mark.native


def test_open_count_and_page_geometry(pdf_path):
    with pyjpdfium.open_document(pdf_path) as doc:
        assert doc.page_count == 4
        with doc.page(1) as page:
            assert page.index == 1
            assert page.size == pyjpdfium.PageSize(612.0, 792.0)
            assert page.rotation == 0


def test_close_is_idempotent_and_closed_objects_are_rejected(pdf_path):
    doc = pyjpdfium.open_document(pdf_path)
    page = doc.page(0)
    page.close()
    page.close()
    assert page.closed
    with pytest.raises(errors.StaleHandleError):
        page.render()
    doc.close()
    doc.close()
    with pytest.raises(errors.StaleHandleError):
        doc.page_count  # noqa: B018


def test_parent_close_is_busy_without_partial_close(pdf_path):
    doc = pyjpdfium.open_document(pdf_path)
    page = doc.page(2)
    with pytest.raises(errors.ResourceBusyError):
        doc.close()
    assert not doc.closed
    assert doc.page_count == 4
    page.close()
    doc.close()
    assert doc.closed


def test_native_rejects_stale_tokens_even_after_slot_reuse(pdf_path):
    from pyjpdfium._loader import native

    lib = native()
    first = lib.doc_open(str(pdf_path), None)
    lib.doc_close(first)
    second = lib.doc_open(str(pdf_path), None)
    try:
        assert first != second
        with pytest.raises(errors.StaleHandleError):
            lib.doc_page_count(first)
        page = lib.page_open(second, 0)
        with pytest.raises(errors.WrongHandleTypeError):
            lib.doc_page_count(page)
        with pytest.raises(errors.InvalidHandleError):
            lib.doc_page_count(0x0100000100FFFFFF)
        lib.page_close(page)
    finally:
        lib.doc_close(second)


def test_input_errors_map_to_exceptions(pdf_path, tmp_path):
    with pytest.raises(errors.PdfIOError):
        pyjpdfium.open_document(tmp_path / "missing.pdf")
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf")
    with pytest.raises(errors.PdfFormatError) as info:
        pyjpdfium.open_document(junk)
    assert info.value.status_name == "JPDF_E_FORMAT"
    with pyjpdfium.open_document(pdf_path) as doc:
        with pytest.raises(errors.PageNotFoundError):
            doc.page(4)
        with pytest.raises(IndexError):
            doc.page(-1)


def test_unicode_path(tmp_path):
    from conftest import fixture_pdf

    path = tmp_path / "dokument-üß-文件.pdf"
    path.write_bytes(fixture_pdf())
    with pyjpdfium.open_document(path) as doc:
        assert doc.page_count == 4


def test_unreferenced_objects_are_reclaimed(pdf_path):
    before = pyjpdfium.runtime_info()
    doc = pyjpdfium.open_document(pdf_path)
    doc.page(0)
    doc.page(1).render()
    del doc
    gc.collect()
    after = pyjpdfium.runtime_info()
    assert after.live_documents == before.live_documents
    assert after.live_pages == before.live_pages
    assert after.live_bitmaps == before.live_bitmaps
