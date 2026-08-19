"""Task 14 packaging boundaries for the optional extension."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]


def _metadata() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_extension_requires_the_core_floor_and_supported_egglog() -> None:
    project = _metadata()["project"]
    requirements = {
        re.match(r"^[A-Za-z0-9_.-]+", value).group(0)
        .lower()
        .replace("_", "-"): value
        for value in project["dependencies"]
    }

    assert requirements["d810-ng"] == "d810-ng>=1.0.0b2"
    assert requirements["egglog"] == "egglog==13.2.0"
    assert "cloudpickle" not in requirements


def test_extension_entry_point_is_exact() -> None:
    project = _metadata()["project"]
    assert project["entry-points"]["d810.backends"] == {
        "egglog": "d810_egglog:MANIFEST"
    }


def test_profiles_and_baselines_are_declared_as_package_resources() -> None:
    package_data = _metadata()["tool"]["setuptools"]["package-data"]
    patterns = [pattern for values in package_data.values() for pattern in values]

    assert "profiles/*.json" in patterns
    assert any("baseline" in pattern.lower() for pattern in patterns)


def test_packaged_resource_directories_exist() -> None:
    assert (ROOT / "src/d810_egglog/profiles").is_dir()
    assert (ROOT / "src/d810_egglog/baselines").is_dir()
    assert list((ROOT / "src/d810_egglog/profiles").glob("*.json"))
    assert list((ROOT / "src/d810_egglog/baselines").glob("*.json"))


def test_extension_wheel_metadata_record_resources_and_installation(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    output_dir.mkdir()
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    wheels = sorted(output_dir.glob("d810_egglog-*.whl"))
    assert len(wheels) == 1
    with ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
        assert "Requires-Python: >=3.11" in metadata
        assert "Requires-Dist: d810-ng>=1.0.0b2" in metadata
        assert "Requires-Dist: egglog==13.2.0" in metadata
        assert "Requires-Dist: cloudpickle" not in metadata
        assert not any(name.startswith("d810/") for name in names)

        resources = {
            name
            for name in names
            if ("/profiles/" in name or "/baselines/" in name) and name.endswith(".json")
        }
        assert len(resources) == 9
        assert any(name.endswith("/profiles/egglog_add_spike.json") for name in resources)
        assert any(
            name.endswith("/baselines/egglog_mba_performance_baseline.json")
            for name in resources
        )

        entry_point_name = next(name for name in names if name.endswith("entry_points.txt"))
        assert archive.read(entry_point_name).decode("utf-8") == (
            "[d810.backends]\n"
            "egglog = d810_egglog:MANIFEST\n"
        )

        record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
        record_names = {
            line.split(",", 1)[0]
            for line in archive.read(record_name).decode("utf-8").splitlines()
        }
        assert names <= record_names

    virtualenv = tmp_path / "venv"
    create = subprocess.run(
        [sys.executable, "-m", "venv", str(virtualenv)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert create.returncode == 0, create.stdout + create.stderr
    python = virtualenv / "bin/python"
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    probe = subprocess.run(
        [
            str(python),
            "-c",
            (
                "from importlib.metadata import entry_points; "
                "from importlib.resources import files; "
                "import d810_egglog; "
                "entries = tuple(entry_points(group='d810.backends')); "
                "assert [(entry.name, entry.value) for entry in entries] == "
                "[('egglog', 'd810_egglog:MANIFEST')]; "
                "assert files('d810_egglog.profiles').joinpath('egglog_add_spike.json').is_file(); "
                "assert files('d810_egglog.baselines').joinpath("
                "'egglog_mba_performance_baseline.json').is_file()"
            ),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
