"""Lazy Egglog dependency and version probe for d810's backend registry."""

from __future__ import annotations

import importlib
import importlib.metadata

SUPPORTED_EGGLOG_VERSION = "13.2.0"


def _unsupported_version_reason(observed: str) -> str:
    return (
        f"unsupported egglog version {observed!r}; this backend supports "
        f"Egglog {SUPPORTED_EGGLOG_VERSION}. Install d810-egglog with a "
        "compatible Egglog release."
    )


def _missing_runtime_reason() -> str:
    return (
        "Egglog is not installed; install d810-egglog (which provides "
        f"Egglog {SUPPORTED_EGGLOG_VERSION}) to enable the mba-egraph backend."
    )


def d810_backend_probe() -> str | None:
    """Return ``None`` when the supported Egglog runtime is importable.

    Expected optional-dependency absence is reported as a reason so D810 can
    classify the backend as unavailable.  Unexpected exceptions deliberately
    propagate; the registry must classify those as broken rather than hiding a
    defect behind an unavailable status.
    """

    try:
        observed = importlib.metadata.version("egglog")
    except importlib.metadata.PackageNotFoundError:
        return _missing_runtime_reason()

    if observed != SUPPORTED_EGGLOG_VERSION:
        return _unsupported_version_reason(observed)

    try:
        importlib.import_module("egglog")
    except ImportError as exc:
        return (
            f"Egglog {observed} is installed but could not be imported: {exc}. "
            f"Install d810-egglog with Egglog {SUPPORTED_EGGLOG_VERSION}."
        )
    return None


__all__ = ["SUPPORTED_EGGLOG_VERSION", "d810_backend_probe"]
