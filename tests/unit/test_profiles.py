"""Config-v2 contracts for packaged Egglog profiles."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest


_PROFILE_NAMES = (
    "egglog_add_spike.json",
    "egglog_mba_families_spike.json",
    "mba_compiler_shape_egglog.json",
    "mba_compiler_shape_egglog_degree2.json",
    "mba_compiler_shape_egglog_profile.json",
    "mba_portfolio_spike.json",
    "mba_portfolio_deep.json",
    "mba_portfolio_telemetry_3ms.json",
)


def _profile_path(name: str) -> Path:
    resource = files("d810_egglog.profiles").joinpath(name)
    assert resource.is_file(), f"missing packaged profile: {name}"
    # The current test installation is a filesystem package. The production
    # README uses Traversable/read_bytes for wheel/zip-safe copying.
    path = Path(resource)
    assert path.is_file()
    return path


def test_every_profile_is_packaged_and_uses_the_hard_cut_pass() -> None:
    for name in _PROFILE_NAMES:
        path = _profile_path(name)
        payload = json.loads(path.read_text(encoding="utf-8"))
        pipeline = payload["additional_configuration"]["pipeline_v2"]
        assert pipeline
        assert all(
            entry["pass_id"] == "mba-egraph"
            or name.startswith("mba_portfolio_")
            and entry["pass_id"] == "mba-simplify"
            for entry in pipeline
        )
        assert any(entry["pass_id"] == "mba-egraph" for entry in pipeline)
        assert "mba-egglog" not in json.dumps(payload)


@pytest.mark.parametrize("name", _PROFILE_NAMES)
def test_profile_loads_through_d810_config_v2_parser(name: str) -> None:
    from d810.core.config import ProjectConfiguration
    from d810.passes.pipeline_config_parser import pipeline_configs_from_project_config

    path = _profile_path(name)
    project = ProjectConfiguration.from_file(path)
    configs = pipeline_configs_from_project_config(project)

    assert configs
    assert "mba-egraph" in {config.pass_id for config in configs}


def test_profile_resource_installation_is_explicit_and_deterministic() -> None:
    readme = Path(__file__).parents[2] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert 'files("d810_egglog.profiles")' in text
    assert "auto-discover" in text.lower()
