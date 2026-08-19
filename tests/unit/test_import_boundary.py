"""Executable contract for the extension's narrow D810 import boundary."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path


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
    core_src = (
        Path(configured)
        if configured
        else EXTENSION_ROOT.parent / "egglog-extension-extraction" / "src"
    )
    assert core_src.is_dir(), f"core source root does not exist: {core_src}"
    return core_src


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
