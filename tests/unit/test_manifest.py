"""Contract tests for the cheap d810-egglog entry-point manifest."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path


def test_manifest_has_the_exact_backend_declaration() -> None:
    from d810_egglog import MANIFEST

    assert MANIFEST == {
        "name": "egglog",
        "api_version": 1,
        "provides": "d810_egglog.runtime",
        "rules": ("d810_egglog.rules.egglog_optimizer",),
        "implements": {"mba-egraph": "EgglogOptimizer"},
    }


def test_project_metadata_declares_the_runtime_python_floor() -> None:
    extension_root = Path(__file__).parents[2]
    metadata = tomllib.loads(
        (extension_root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert metadata["project"]["requires-python"] == ">=3.11"


def test_root_manifest_import_does_not_load_runtime_or_optional_dependencies() -> None:
    extension_root = Path(__file__).parents[2]
    core_root = os.environ.get("D810_EGGLOG_CORE_SRC", "")
    script = """
import sys
import d810_egglog

assert d810_egglog.MANIFEST["name"] == "egglog"
for module in (
    "egglog",
    "d810_egglog.runtime",
    "d810_egglog.rules",
    "d810_egglog.rules.egglog_optimizer",
    "d810.manager",
    "d810.ui",
):
    assert module not in sys.modules, module
"""
    env = dict(os.environ)
    inherited = [value for value in (core_root, env.get("PYTHONPATH", "")) if value]
    env["PYTHONPATH"] = os.pathsep.join((str(extension_root / "src"), *inherited))
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
