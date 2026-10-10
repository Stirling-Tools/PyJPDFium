import pytest

from pyjpdfium import errors


def test_unknown_status_is_never_success():
    exc = errors._from_status(-1234, "JPDF_E_UNKNOWN", "")
    assert isinstance(exc, errors.InternalError)
    assert exc.status == -1234


def test_detail_and_name_in_message():
    exc = errors._from_status(-3, "JPDF_E_STALE_HANDLE", "page handle rejected")
    assert isinstance(exc, errors.StaleHandleError)
    assert isinstance(exc, errors.HandleError)
    assert str(exc) == "page handle rejected (JPDF_E_STALE_HANDLE)"
    assert exc.status_name == "JPDF_E_STALE_HANDLE"


@pytest.mark.parametrize(
    ("status", "builtin"),
    [
        (-1, ValueError),
        (-4, TypeError),
        (-7, OSError),
        (-10, IndexError),
        (-12, MemoryError),
        (-21, TimeoutError),
    ],
)
def test_builtin_bases_construct_and_catch(status, builtin):
    exc = errors._from_status(status, "X", "detail")
    assert isinstance(exc, builtin)
    with pytest.raises(builtin):
        raise exc


@pytest.mark.native
def test_table_covers_every_compiled_status():
    from pyjpdfium._loader import native

    for name, code in native().STATUS.items():
        if code == 0:
            continue
        assert code in errors.STATUS_ERRORS, name
