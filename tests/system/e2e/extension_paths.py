"""Paths shared by extension-owned native evidence tests."""

from __future__ import annotations

import os
from pathlib import Path


EXTENSION_ROOT = Path(__file__).resolve().parents[3]
_CONTAINER_CORE_ROOT = Path("/work")
CORE_ROOT = (
    _CONTAINER_CORE_ROOT
    if (_CONTAINER_CORE_ROOT / "src").is_dir()
    else Path(
        os.environ.get(
            "D810_EGGLOG_CORE_ROOT",
            EXTENSION_ROOT.parent / "egglog-extension-extraction",
        )
    )
)
