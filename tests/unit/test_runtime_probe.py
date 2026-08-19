"""Tests for the lazy Egglog runtime availability probe."""

from __future__ import annotations

import importlib
import importlib.metadata

import pytest


def _runtime_module():
    from d810_egglog import runtime

    return runtime


def test_supported_13_2_release_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime_module()
    imported: list[str] = []

    monkeypatch.setattr(importlib.metadata, "version", lambda distribution: "13.2.0")
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name) or object(),
    )

    assert runtime.SUPPORTED_EGGLOG_VERSION == "13.2.0"
    assert runtime.d810_backend_probe() is None
    assert imported == ["egglog"]


@pytest.mark.parametrize("observed", ["13.1.9", "13.2.1", "13.3.0", "14.0.0"])
def test_unsupported_version_returns_actionable_reason(
    monkeypatch: pytest.MonkeyPatch, observed: str
) -> None:
    runtime = _runtime_module()
    imported: list[str] = []

    monkeypatch.setattr(importlib.metadata, "version", lambda distribution: observed)
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name) or object(),
    )

    reason = runtime.d810_backend_probe()

    assert reason is not None
    assert observed in reason
    assert "13.2" in reason
    assert "egglog" in reason.lower()
    assert "install" in reason.lower()
    assert imported == []


def test_missing_distribution_returns_actionable_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime_module()

    def missing(distribution: str) -> str:
        raise importlib.metadata.PackageNotFoundError(distribution)

    monkeypatch.setattr(importlib.metadata, "version", missing)

    reason = runtime.d810_backend_probe()

    assert reason is not None
    assert "egglog" in reason.lower()
    assert "install" in reason.lower()
    assert "13.2" in reason


def test_import_failure_returns_actionable_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime_module()
    monkeypatch.setattr(importlib.metadata, "version", lambda distribution: "13.2.0")

    def unavailable(name: str) -> object:
        raise ImportError("native module missing")

    monkeypatch.setattr(importlib, "import_module", unavailable)

    reason = runtime.d810_backend_probe()

    assert reason is not None
    assert "egglog" in reason.lower()
    assert "install" in reason.lower()
    assert "native module missing" in reason


def test_unexpected_version_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime_module()

    def broken(distribution: str) -> str:
        raise RuntimeError("metadata backend exploded")

    monkeypatch.setattr(importlib.metadata, "version", broken)

    with pytest.raises(RuntimeError, match="metadata backend exploded"):
        runtime.d810_backend_probe()


def test_unexpected_import_error_propagates_as_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime_module()
    monkeypatch.setattr(importlib.metadata, "version", lambda distribution: "13.2.0")

    def broken(name: str) -> object:
        raise RuntimeError("egglog import exploded")

    monkeypatch.setattr(importlib, "import_module", broken)

    with pytest.raises(RuntimeError, match="egglog import exploded"):
        runtime.d810_backend_probe()
