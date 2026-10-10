import subprocess
import sys

import pytest

pytestmark = pytest.mark.native

# Shutdown is final for a process, so it runs in a fresh interpreter.
PROBE = """
import sys
import pyjpdfium
from pyjpdfium import errors, RuntimeState

doc = pyjpdfium.open_document(sys.argv[1])
page = doc.page(0)
bitmap = page.render(dpi=10, pixel_format="gray")
try:
    pyjpdfium.shutdown()
except errors.ResourceBusyError as exc:
    assert "1 documents and 1 pages" in str(exc), exc
else:
    raise AssertionError("shutdown with live pages must be refused")
assert pyjpdfium.runtime_info().state is RuntimeState.QUIESCING
try:
    pyjpdfium.open_document(sys.argv[1])
except errors.RuntimeStateError as exc:
    assert exc.status_name == "JPDF_E_QUIESCING"
else:
    raise AssertionError("no new work while quiescing")
page.close()
doc.close()
pyjpdfium.shutdown()
assert pyjpdfium.runtime_info().state is RuntimeState.STOPPED
try:
    pyjpdfium.open_document(sys.argv[1])
except errors.RuntimeStateError as exc:
    assert exc.status_name == "JPDF_E_STOPPED"
else:
    raise AssertionError("stopped is final")
assert len(bitmap.tobytes()) == 85 * 110
bitmap.close()
print("shutdown-ok")
"""


def test_shutdown_lifecycle(pdf_path):
    result = subprocess.run(
        [sys.executable, "-c", PROBE, str(pdf_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "shutdown-ok" in result.stdout
