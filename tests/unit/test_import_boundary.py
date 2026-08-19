"""Executable contract for the extension's narrow D810 import boundary."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path


EXTENSION_ROOT = Path(__file__).parents[2]
CONTRACT_SECTION = "importlinter:contract:extension-d810-direct-boundary"
ALLOWED_D810_IMPORTS = (
    "d810_egglog.** -> d810.mba.extension_api",
    "d810_egglog.** -> d810.backends.mba.extension_host",
    ("d810_egglog.** -> d810.optimizers.microcode.instructions.peephole.handler"),
)


def _contract_config() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    with (EXTENSION_ROOT / ".importlinter").open(encoding="utf-8") as stream:
        parser.read_file(stream)
    return parser[CONTRACT_SECTION]


def _run_direct_boundary_contract(
    import_statement: str,
) -> subprocess.CompletedProcess[str]:
    probe = EXTENSION_ROOT / "src/d810_egglog/_boundary_contract_probe.py"
    probe.write_text(f"{import_statement}\n", encoding="utf-8")
    try:
        lint_imports = shutil.which("lint-imports")
        assert lint_imports is not None, "lint-imports must be installed for this test"
        env = dict(os.environ)
        core_src = Path(__file__).parents[4] / "egglog-extension-extraction/src"
        python_path = [str(core_src), str(EXTENSION_ROOT / "src")]
        if env.get("PYTHONPATH"):
            python_path.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(python_path)
        return subprocess.run(
            [
                lint_imports,
                "--config",
                str(EXTENSION_ROOT / ".importlinter"),
                "--contract",
                "extension-d810-direct-boundary",
                "--no-cache",
            ],
            cwd=EXTENSION_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        probe.unlink(missing_ok=True)


def test_direct_d810_boundary_has_only_the_three_approved_edges() -> None:
    config = _contract_config()

    assert config["forbidden_modules"].split() == ["d810"]
    assert config["allow_indirect_imports"].lower() == "true"
    assert config["unmatched_ignore_imports_alerting"].lower() == "none"
    actual = tuple(
        line.strip() for line in config["ignore_imports"].splitlines() if line.strip()
    )
    assert actual == ALLOWED_D810_IMPORTS


def test_approved_d810_edges_pass_but_arbitrary_d810_import_fails() -> None:
    for import_statement in (
        "import d810.mba.extension_api",
        "import d810.backends.mba.extension_host",
        "import d810.optimizers.microcode.instructions.peephole.handler",
    ):
        result = _run_direct_boundary_contract(import_statement)
        assert result.returncode == 0, result.stdout + result.stderr

    result = _run_direct_boundary_contract("import d810.core.typing")
    assert result.returncode != 0
    assert "d810.core.typing" in result.stdout + result.stderr
