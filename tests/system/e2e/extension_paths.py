"""Paths shared by extension-owned native evidence tests."""

from __future__ import annotations

import os
from pathlib import Path


EXTENSION_ROOT = Path(__file__).resolve().parents[3]
_CONTAINER_CORE_ROOT = Path("/work")
CORE_ROOT = _CONTAINER_CORE_ROOT if (_CONTAINER_CORE_ROOT / "src").is_dir() else None
if CORE_ROOT is None:
    configured_core_root = os.environ.get("D810_EGGLOG_CORE_ROOT")
    if not configured_core_root:
        raise RuntimeError(
            "D810_EGGLOG_CORE_ROOT must point to the core checkout when /work "
            "is unavailable"
        )
    CORE_ROOT = Path(configured_core_root).expanduser().resolve()
if not (CORE_ROOT / "src").is_dir():
    raise RuntimeError(f"core checkout does not contain src/: {CORE_ROOT}")
