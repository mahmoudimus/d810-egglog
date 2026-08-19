"""Task 14 packaging boundaries for the optional extension."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


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
    assert requirements["egglog"] == "egglog>=13.2.0,<14"
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
