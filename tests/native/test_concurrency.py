import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import pyjpdfium
from pyjpdfium import errors

pytestmark = pytest.mark.native

THREADS = 8


def render_bytes(page, dpi=36):
    with page.render(dpi=dpi, pixel_format="gray") as bitmap:
        return bitmap.tobytes()


def test_independent_documents_render_identically(pdf_path):
    expected = {}
    with pyjpdfium.open_document(pdf_path) as doc:
        for i in range(4):
            with doc.page(i) as page:
                expected[i] = render_bytes(page)

    def work(n):
        index = n % 4
        with pyjpdfium.open_document(pdf_path) as doc, doc.page(index) as page:
            return index, render_bytes(page)

    with ThreadPoolExecutor(THREADS) as pool:
        results = list(pool.map(work, range(200)))
    assert all(data == expected[index] for index, data in results)


def test_one_shared_document_across_threads(pdf_path):
    # The native domain owns serialization, so one document can be shared across threads.
    with pyjpdfium.open_document(pdf_path) as doc:
        pages = [doc.page(i) for i in range(4)]
        expected = [render_bytes(p, 150) for p in pages]
        before = pyjpdfium.runtime_info()
        with ThreadPoolExecutor(THREADS) as pool:
            results = list(pool.map(lambda n: (n % 4, render_bytes(pages[n % 4], 150)), range(64)))
        after = pyjpdfium.runtime_info()
        for p in pages:
            p.close()
    assert expected[0] != expected[1]
    assert all(data == expected[index] for index, data in results)
    # Threads only queue on the domain when the GIL is released around the native call.
    assert after.domain_wait_ns - before.domain_wait_ns > 1_000_000


def test_close_race_only_succeeds_or_reports_stale(pdf_path):
    stale = 0
    for _ in range(50):
        doc = pyjpdfium.open_document(pdf_path)
        page = doc.page(0)
        start = threading.Barrier(5)
        outcomes = []

        def renderer():
            start.wait()
            for _ in range(5):
                try:
                    page.render(dpi=18, pixel_format="gray").close()
                    outcomes.append("ok")
                except errors.StaleHandleError:
                    outcomes.append("stale")

        def closer():
            start.wait()
            page.close()
            doc.close()

        threads = [threading.Thread(target=renderer) for _ in range(4)]
        threads.append(threading.Thread(target=closer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert set(outcomes) <= {"ok", "stale"}
        assert len(outcomes) == 20
        stale += outcomes.count("stale")
    assert stale > 0
    info = pyjpdfium.runtime_info()
    assert info.live_pages == 0
