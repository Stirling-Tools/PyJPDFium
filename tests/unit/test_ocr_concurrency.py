import threading
import time

import pytest

from pyjpdfium import errors, ocr


class FakeNative:
    """Stands in for the OCR extension and records how many recognitions overlap."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = self.peak = 0

    def engine_open(self, profile, threads):
        return 1

    def engine_info(self, token):
        return "fake", "0"

    def engine_close(self, token):
        pass

    def recognize(self, engine, bitmap, max_pixels):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        return 10, 10, 300.0, 300.0, []


class FakeBitmap:
    def _require_open(self):
        return 7


@pytest.mark.parametrize(("limit", "peak"), [(None, 6), (1, 1), (2, 2)])
def test_max_concurrent_bounds_overlapping_recognitions(monkeypatch, limit, peak):
    fake = FakeNative()
    monkeypatch.setattr(ocr, "ocr_native", lambda: fake)
    engine = ocr.OcrEngine("profile", max_concurrent=limit)
    threads = [threading.Thread(target=engine._recognize, args=(FakeBitmap(), None))
               for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert fake.peak == peak


def test_max_concurrent_must_be_positive(monkeypatch):
    monkeypatch.setattr(ocr, "ocr_native", FakeNative)
    with pytest.raises(errors.InvalidArgumentError):
        ocr.OcrEngine("profile", max_concurrent=0)
