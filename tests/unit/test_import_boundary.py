"""Executable contract for the extension's narrow D810 import boundary."""

from __future__ import annotations

import configparser
import importlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest


EXTENSION_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SECTION = "importlinter:contract:extension-d810-direct-boundary"
ALLOWED_D810_IMPORTS = (
    "d810_egglog.** -> d810.mba.extension_api",
    "d810_egglog.** -> d810.backends.mba.extension_host",
    ("d810_egglog.** -> d810.optimizers.microcode.instructions.peephole.handler"),
)


def _production_contract() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    with (EXTENSION_ROOT / ".importlinter").open(encoding="utf-8") as stream:
        parser.read_file(stream)
    return parser[CONTRACT_SECTION]


def _core_source_root() -> Path:
    configured = os.environ.get("D810_EGGLOG_CORE_SRC")
    if configured:
        core_src = Path(configured).expanduser().resolve()
    else:
        try:
            d810 = importlib.import_module("d810")
        except ImportError as exc:
            raise AssertionError(
                "D810_EGGLOG_CORE_SRC must point to the core src directory "
                "when d810 is not importable"
            ) from exc
        package_file = getattr(d810, "__file__", None)
        if package_file is None:
            raise AssertionError(
                "D810_EGGLOG_CORE_SRC must point to the core src directory "
                "when d810 has no filesystem package"
            )
        core_src = Path(package_file).resolve().parent.parent
    assert core_src.is_dir(), f"core source root does not exist: {core_src}"
    assert (core_src / "d810").is_dir(), f"not a d810 source root: {core_src}"
    return core_src


def test_core_source_resolution_fails_closed_without_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("D810_EGGLOG_CORE_SRC", str(EXTENSION_ROOT / "missing-core-src"))
    with pytest.raises(AssertionError, match="core source root does not exist"):
        _core_source_root()


def test_system_bootstrap_core_resolution_is_explicit() -> None:
    for relative_path in (
        Path("tests/system/conftest.py"),
        Path("tests/system/e2e/extension_paths.py"),
    ):
        source = (EXTENSION_ROOT / relative_path).read_text(encoding="utf-8")
        assert "D810_EGGLOG_CORE_ROOT" in source
        assert "if not configured_core_root" in source
        assert "raise RuntimeError" in source


def _write_probe_project(
    tmp_path: Path,
    import_statements: tuple[str, ...],
) -> tuple[Path, Path]:
    project_root = tmp_path / "import-boundary-project"
    extension_src = project_root / "src" / "d810_egglog"
    extension_src.mkdir(parents=True)
    (extension_src / "__init__.py").write_text("", encoding="utf-8")
    (extension_src / "_boundary_contract_probe.py").write_text(
        "\n".join((*import_statements, "")),
        encoding="utf-8",
    )
    return project_root, extension_src.parent


def _write_contract_config(project_root: Path) -> Path:
    production = _production_contract()
    config = configparser.ConfigParser()
    config["importlinter"] = {
        "root_packages": "d810\nd810_egglog",
        "include_external_packages": "True",
        "exclude_type_checking_imports": "True",
    }
    config[CONTRACT_SECTION] = {
        key: production[key]
        for key in (
            "name",
            "type",
            "allow_indirect_imports",
            "source_modules",
            "forbidden_modules",
            "ignore_imports",
            "unmatched_ignore_imports_alerting",
        )
    }
    config_path = project_root / ".importlinter"
    with config_path.open("w", encoding="utf-8") as stream:
        config.write(stream)
    return config_path


def _run_direct_boundary_contract(
    tmp_path: Path,
    import_statements: tuple[str, ...],
) -> subprocess.CompletedProcess[str]:
    project_root, extension_src = _write_probe_project(tmp_path, import_statements)
    config_path = _write_contract_config(project_root)
    lint_imports = shutil.which("lint-imports")
    assert lint_imports is not None, "lint-imports must be installed for this test"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join((str(extension_src), str(_core_source_root()))),
    }
    return subprocess.run(
        [
            lint_imports,
            "--config",
            str(config_path),
            "--contract",
            "extension-d810-direct-boundary",
            "--no-cache",
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_direct_d810_boundary_has_only_the_three_approved_edges() -> None:
    config = _production_contract()

    assert config["forbidden_modules"].split() == ["d810"]
    assert config["allow_indirect_imports"].lower() == "true"
    assert config["unmatched_ignore_imports_alerting"].lower() == "none"
    actual = tuple(
        line.strip() for line in config["ignore_imports"].splitlines() if line.strip()
    )
    assert actual == ALLOWED_D810_IMPORTS


def test_approved_d810_edges_pass_but_arbitrary_d810_import_fails(
    tmp_path: Path,
) -> None:
    approved = _run_direct_boundary_contract(
        tmp_path / "approved",
        (
            "import d810.mba.extension_api",
            "import d810.backends.mba.extension_host",
            "import d810.optimizers.microcode.instructions.peephole.handler",
        ),
    )
    assert approved.returncode == 0, approved.stdout + approved.stderr

    arbitrary = _run_direct_boundary_contract(
        tmp_path / "arbitrary",
        ("import d810.core.typing",),
    )
    assert arbitrary.returncode != 0
    assert "d810.core.typing" in arbitrary.stdout + arbitrary.stderr
