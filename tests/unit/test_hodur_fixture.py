"""Integrity contracts for the provider-owned Hodur native fixture."""

from __future__ import annotations

import hashlib
from pathlib import Path


_FIXTURE_ROOT = Path(__file__).parents[1] / "_resources" / "hodur_complement_mask"
_BINARY = _FIXTURE_ROOT / "hodur_egglog_probe.dll"
_SOURCE = _FIXTURE_ROOT / "Hodur_ComplementMaskResidual.asm"
_EXPECTED_SHA256 = "575aea3e22d2fba5be0587e408d497c629e1d6d673bef523f52d49087ff94026"
_EXPORT = "Hodur_ComplementMaskResidual"


def test_hodur_fixture_has_pinned_image_hash_and_source_export() -> None:
    assert _BINARY.is_file()
    assert _SOURCE.is_file()
    assert hashlib.sha256(_BINARY.read_bytes()).hexdigest() == _EXPECTED_SHA256

    source = _SOURCE.read_text(encoding="utf-8")
    assert f"PUBLIC {_EXPORT}" in source
    assert f"{_EXPORT}:" in source


def test_hodur_fixture_provenance_document_matches_resources() -> None:
    readme = (_FIXTURE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "89aa91671536ceda035e224b6f8884a4c8726170" in readme
    assert _EXPECTED_SHA256 in readme
    assert _EXPORT in readme
