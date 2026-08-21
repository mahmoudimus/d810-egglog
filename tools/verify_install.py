"""Prove an installed d810-egglog artifact is discoverable, not merely present.

Run against the built wheel and the built sdist in deploy.yml, before either is
uploaded. It is the pure-Python analogue of d810-CoBRA's ``verify_binding.py``:
that package's failure mode was a wheel that compiled and simplified nothing;
this package's failure mode is a wheel that installs and is never *found*.

Both are silent. d810 discovers this backend through the ``d810.backends``
entry point and reads config-v2 profiles as package resources, so a
distribution can install cleanly, import cleanly, and still be inert because
setuptools was never told to ship the entry point or the JSON. Nothing in
``import d810_egglog`` catches that -- the package root is a dict literal and
imports fine from a broken wheel.

Deliberately NOT checked here: the optimizer, the rule catalogue, the
saturation contracts. All of those import ``d810.mba.extension_api``, which
requires d810-ng>=1.0.0b2 -- unreleased, so the artifact is installed with
``--no-deps`` and d810 is absent. Testing through them would fail on a missing
runtime dependency and say nothing about the artifact.

The probe IS checked, because it is d810-free and is a known-answer question:
``d810_backend_probe()`` returns ``None`` only when the audited Egglog is
actually importable at the pinned version. A boolean "did an import statement
run" would not distinguish a usable runtime from a mismatched one.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import json
import pathlib
import sys

DIST = "d810-egglog"
GROUP = "d810.backends"
BACKEND = "egglog"

#: The tree this script ships beside, used to demand the wheel carries exactly
#: the resources the source carries. Absent when the script is run from an
#: unpacked artifact rather than a checkout, in which case the check falls back
#: to "non-empty", which still catches a package-data regression.
REPO_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "d810_egglog"


def _fail(message: str) -> int:
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def _check_resources(subpackage: str) -> str | None:
    """Return an error string, or ``None`` when the JSON resources are intact."""

    try:
        resources = importlib.resources.files(f"d810_egglog.{subpackage}")
    except ModuleNotFoundError as exc:
        return f"d810_egglog.{subpackage} is not in the installed package: {exc}"

    installed = {r.name for r in resources.iterdir() if r.name.endswith(".json")}
    if not installed:
        return (
            f"the installed d810_egglog.{subpackage} ships no .json resources; "
            "[tool.setuptools.package-data] did not reach the artifact"
        )

    source_dir = REPO_SRC / subpackage
    if source_dir.is_dir():
        expected = {p.name for p in source_dir.glob("*.json")}
        if installed != expected:
            missing = sorted(expected - installed)
            extra = sorted(installed - expected)
            return (
                f"d810_egglog.{subpackage} resources differ from source: "
                f"missing={missing} unexpected={extra}"
            )

    for name in sorted(installed):
        try:
            json.loads((resources / name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return f"d810_egglog.{subpackage}/{name} is not readable JSON: {exc}"

    print(f"resources: {subpackage} OK ({len(installed)} JSON)")
    return None


def main() -> int:
    try:
        dist_version = importlib.metadata.version(DIST)
    except importlib.metadata.PackageNotFoundError:
        return _fail(f"{DIST} is not installed in this environment")

    import d810_egglog

    print(f"package: {d810_egglog.__file__}")
    print(f"version: {dist_version}")

    # Version drift between the metadata and the module is invisible until a
    # user reports a bug against a version that never existed.
    if dist_version != d810_egglog.__version__:
        return _fail(
            f"metadata version {dist_version!r} != "
            f"d810_egglog.__version__ {d810_egglog.__version__!r}"
        )

    # The whole integration surface. Read it back from the INSTALLED metadata
    # rather than from pyproject.toml, which is what makes this a check on the
    # artifact instead of on the source tree.
    # ``EntryPoint.dist`` is populated when the entry point came from an
    # installed distribution, but it is not guaranteed across implementations,
    # so it narrows the lookup only when present rather than gating it.
    entries = {}
    for entry in importlib.metadata.entry_points(group=GROUP):
        dist = getattr(entry, "dist", None)
        if dist is None or dist.name == DIST:
            entries[entry.name] = entry
    if BACKEND not in entries:
        return _fail(
            f"{DIST} registers no {BACKEND!r} entry point in group {GROUP!r}; "
            f"d810 would never discover this backend (found: {sorted(entries)})"
        )

    entry = entries[BACKEND]
    print(f"entry point: {GROUP} -> {entry.name} = {entry.value}")

    manifest = entry.load()
    if manifest is not d810_egglog.MANIFEST:
        return _fail(f"{GROUP} entry point resolved to {manifest!r}, not MANIFEST")

    required = {"name", "api_version", "provides"}
    if not required <= set(manifest):
        return _fail(f"manifest is missing {sorted(required - set(manifest))}: {manifest}")
    if manifest["name"] != BACKEND:
        return _fail(f"manifest name is {manifest['name']!r}, expected {BACKEND!r}")
    if not isinstance(manifest["api_version"], int):
        return _fail(f"manifest api_version must be an int: {manifest}")
    # A string keeps resolution lazy, so an incompatible d810 can reject this
    # backend without importing runtime.py and loading Egglog.
    if not isinstance(manifest["provides"], str):
        return _fail(f"manifest provides must stay a string: {manifest}")
    if manifest.get("implements") != {"mba-egraph": "EgglogOptimizer"}:
        return _fail(f"manifest does not implement mba-egraph: {manifest}")

    for subpackage in ("profiles", "baselines"):
        error = _check_resources(subpackage)
        if error is not None:
            return _fail(error)

    from d810_egglog.runtime import d810_backend_probe

    reason = d810_backend_probe()
    if reason is not None:
        return _fail(f"probe rejected the runtime it is meant to accept: {reason}")

    print("probe: audited Egglog runtime available")
    print(f"OK: {DIST} {dist_version} installs, registers, and probes clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
