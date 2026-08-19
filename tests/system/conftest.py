"""Load the core IDA/runtime fixtures for extension-owned system tests."""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import os
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

import pytest

from d810.core.config import ProjectConfiguration

# The Docker runner mounts the core checkout at /work and the extension at
# /opt/d810-egglog.  Load the core system fixtures by stable aliases rather
# than naming ``tests.system.conftest`` here: this file already owns that
# import path, and pytest rejects registering a plugin under two names.
_CORE_ROOT = Path("/work")
if not (_CORE_ROOT / "tests/system/conftest.py").is_file():
    _CORE_ROOT = Path(
        os.environ.get(
            "D810_EGGLOG_CORE_ROOT",
            Path(__file__).resolve().parents[3].parent / "egglog-extension-extraction",
        )
    )


def _extend_core_test_packages() -> None:
    """Make core test helpers importable while extension tests are collected."""

    tests_package = importlib.import_module("tests")
    tests_paths = getattr(tests_package, "__path__", None)
    if tests_paths is not None and str(_CORE_ROOT / "tests") not in tests_paths:
        tests_paths.append(str(_CORE_ROOT / "tests"))

    # ``tests.system`` and ``tests.system.runtime`` may already be packages
    # from this extension.  Extend their namespace paths before loading the
    # core conftest aliases so imports such as ``tests.system.runtime.support``
    # resolve to the core fixture implementation.
    for package_name, package_path in (
        ("tests.system", _CORE_ROOT / "tests/system"),
        ("tests.system.runtime", _CORE_ROOT / "tests/system/runtime"),
    ):
        try:
            package = importlib.import_module(package_name)
        except ModuleNotFoundError:
            continue
        paths = getattr(package, "__path__", None)
        if paths is not None and str(package_path) not in paths:
            paths.append(str(package_path))


def _load_core_plugin(alias: str, path: Path, import_name: str | None = None) -> str:
    """Load one core conftest under an alias accepted by pytest."""

    _extend_core_test_packages()
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load core pytest plugin {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    if import_name is not None:
        sys.modules[import_name] = module
    spec.loader.exec_module(module)
    return alias


_CORE_SYSTEM_CONFTEST = _CORE_ROOT / "tests/system/conftest.py"
if _CORE_SYSTEM_CONFTEST.is_file():
    pytest_plugins = (
        _load_core_plugin(
            "d810_egglog._core_tests_conftest",
            _CORE_ROOT / "tests/conftest.py",
            import_name="tests.conftest",
        ),
        _load_core_plugin("d810_egglog._core_system_conftest", _CORE_SYSTEM_CONFTEST),
        _load_core_plugin(
            "d810_egglog._core_runtime_conftest",
            _CORE_ROOT / "tests/system/runtime/conftest.py",
        ),
    )
else:
    pytest_plugins = ()


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


@contextlib.contextmanager
def _extension_state_cm():
    """Add packaged profiles to the per-test manager without core fixtures."""

    core_conftest = sys.modules["d810_egglog._core_system_conftest"]

    with tempfile.TemporaryDirectory(prefix="d810-egglog-profiles-") as root:
        profile_root = Path(root)
        for name in _PROFILE_NAMES:
            resource = files("d810_egglog.profiles").joinpath(name)
            path = profile_root / name
            path.write_bytes(resource.read_bytes())
        with core_conftest._d810_state_cm() as state:
            for name in _PROFILE_NAMES:
                path = profile_root / name
                state.add_project(ProjectConfiguration.from_file(path))
            yield state


@pytest.fixture
def d810_state():
    """Use core IDA lifecycle fixtures while explicitly staging extension profiles."""

    return _extension_state_cm
