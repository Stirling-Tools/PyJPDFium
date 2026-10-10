"""Exceptions mapped from JPDFium native status codes. Pure Python; loads nothing native."""

from __future__ import annotations


class PyJPDFiumError(Exception):
    """Base class. ``status`` is the native code, or None for errors raised in Python."""

    def __init__(
        self, message: str, *, status: int | None = None, status_name: str | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.status_name = status_name


class NativeLoadError(PyJPDFiumError):
    """The native core is missing, incompatible or loaded more than once."""


class InvalidArgumentError(PyJPDFiumError, ValueError):
    pass


class HandleError(PyJPDFiumError):
    """A native handle was rejected before it was dereferenced."""


class InvalidHandleError(HandleError):
    pass


class StaleHandleError(HandleError):
    """The object was closed; its handle can never become valid again."""


class WrongHandleTypeError(HandleError, TypeError):
    pass


class ResourceBusyError(PyJPDFiumError):
    """Close or shutdown refused while dependents remain; nothing was changed."""


class UnsupportedError(PyJPDFiumError):
    pass


class PdfIOError(PyJPDFiumError, OSError):
    pass


class PasswordError(PyJPDFiumError):
    pass


class PdfFormatError(PyJPDFiumError):
    pass


class PageNotFoundError(PyJPDFiumError, IndexError):
    pass


class LimitExceededError(PyJPDFiumError):
    pass


class NativeMemoryError(PyJPDFiumError, MemoryError):
    pass


class RuntimeStateError(PyJPDFiumError):
    """The runtime is not initialized, is quiescing, stopped, failed, or owned elsewhere."""


class ReentrancyError(PyJPDFiumError):
    pass


class OperationCancelledError(PyJPDFiumError):
    pass


class OperationTimeoutError(PyJPDFiumError, TimeoutError):
    pass


class InternalError(PyJPDFiumError):
    pass


# Mirrors jpdfium_api.h; tests check it against the codes compiled into the extension.
STATUS_ERRORS: dict[int, type[PyJPDFiumError]] = {
    -1: InvalidArgumentError,
    -2: InvalidHandleError,
    -3: StaleHandleError,
    -4: WrongHandleTypeError,
    -5: ResourceBusyError,
    -6: UnsupportedError,
    -7: PdfIOError,
    -8: PasswordError,
    -9: PdfFormatError,
    -10: PageNotFoundError,
    -11: LimitExceededError,
    -12: NativeMemoryError,
    -13: InternalError,
    -14: RuntimeStateError,
    -15: RuntimeStateError,
    -16: RuntimeStateError,
    -17: RuntimeStateError,
    -18: RuntimeStateError,
    -19: ReentrancyError,
    -20: OperationCancelledError,
    -21: OperationTimeoutError,
    -99: InternalError,
}


def _from_status(status: int, name: str, detail: str) -> PyJPDFiumError:
    # Unknown codes are never success: they surface as internal errors.
    cls = STATUS_ERRORS.get(status, InternalError)
    message = f"{detail} ({name})" if detail else name
    return cls(message, status=status, status_name=name)
