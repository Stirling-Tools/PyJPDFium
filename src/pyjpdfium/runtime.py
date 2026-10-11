"""Runtime identity, capabilities and explicit lifecycle control."""

from __future__ import annotations

from ._loader import native
from .models import Capability, Renderer, RuntimeInfo, RuntimeState


def runtime_info() -> RuntimeInfo:
    raw = native().runtime_info()
    renderer = raw["renderer"]
    return RuntimeInfo(
        state=RuntimeState(raw["state"]),
        api_version=tuple(raw["api_version"]),
        renderer=Renderer(renderer) if renderer >= 0 else None,
        build_id=raw["build_id"],
        live_documents=raw["live_documents"],
        live_pages=raw["live_pages"],
        live_bitmaps=raw["live_bitmaps"],
        live_views=raw["live_views"],
        domain_acquisitions=raw["domain_acquisitions"],
        domain_wait_ns=raw["domain_wait_ns"],
        domain_hold_ns=raw["domain_hold_ns"],
    )


def capability(name: str) -> Capability:
    """Readiness of a named operation such as ``"pdf.render"``."""
    return Capability(native().capability(name))


def quiesce() -> None:
    """Stops admitting new work; open pages and documents can still be closed."""
    native().runtime_quiesce()


def shutdown() -> None:
    """Destroys PDFium once nothing is open. Final for this process.

    Raises ResourceBusyError, leaving the runtime quiescing, while documents or pages are open.
    """
    native().runtime_shutdown()
