# d810-egglog

[![ci](https://github.com/mahmoudimus/d810-egglog/actions/workflows/ci.yml/badge.svg)](https://github.com/mahmoudimus/d810-egglog/actions/workflows/ci.yml)
[![deploy](https://github.com/mahmoudimus/d810-egglog/actions/workflows/deploy.yml/badge.svg)](https://github.com/mahmoudimus/d810-egglog/actions/workflows/deploy.yml)
[![pypi](https://img.shields.io/pypi/v/d810-egglog.svg)](https://pypi.org/project/d810-egglog/)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![d810-ng](https://img.shields.io/badge/d810--ng-backend-8A2BE2.svg)](https://github.com/w00tzenheimer/d810-ng)

`d810-egglog` is the optional Egglog implementation of d810-ng's
backend-neutral `mba-egraph` pass.  Installing this distribution registers the
`egglog` backend through the `d810.backends` entry-point group.

The package contains the optimizer, its declared rule module, and test-only
config-v2 profiles. The probe accepts the audited Egglog 13.2.0 runtime and
reports an actionable reason when the optional runtime is absent or cannot be
imported.

Install it alongside d810-ng when the e-graph backend is needed:

```bash
python -m pip install d810-egglog
```

> **Requires `d810-ng >= 1.0.0b2`, which is not released yet.**
> Every module this backend runs -- `saturation`, `rule_lowering`,
> `composite_rewrite`, the optimizer -- imports `d810.mba.extension_api`, and
> the optimizer also needs `d810.backends.mba.extension_host`. d810-ng 0.6.6
> ships neither, so pip will refuse to install this package against it,
> deliberately. The floor is `1.0.0b2` rather than `1.0.0` because a
> pre-release sorts *before* its final, so `>=1.0.0` would reject every beta.
> A loud version error at install time beats a backend that installs and then
> fails on import the first time a project selects `mba-egraph`.

Installation registers the `egglog` backend in D810's `d810.backends`
entry-point group. Core discovers the declaration without importing the
runtime; when a project selects `mba-egraph`, D810 probes Egglog first and
then loads the declared `EgglogOptimizer` rule. If the provider is absent or
unavailable, selection fails with an actionable install/probe error.

Profiles are package resources, not D810 project-manager entries. Install a
profile explicitly into the D810 configuration directory when you want to use
one from the IDA UI or a project manager:

```bash
python - <<'PY'
from importlib.resources import files
from pathlib import Path

destination = Path.home() / ".idapro" / "cfg" / "d810"
destination.mkdir(parents=True, exist_ok=True)
resources = files("d810_egglog.profiles")
for resource in sorted(resources.iterdir(), key=lambda item: item.name):
    if resource.name.endswith(".json"):
        (destination / resource.name).write_bytes(resource.read_bytes())
PY
```

The current D810 manifest and UI do not auto-discover package resources. The
copy step is deliberate: it makes the selected profile and its provenance
visible in the ordinary config-v2 project workflow. All packaged profiles use
the hard-cut `mba-egraph` pass; legacy pass spellings are not accepted.

The provider-owned performance baseline is also a package resource at
`d810_egglog.baselines/egglog_mba_performance_baseline.json`. It is kept
separate from project-manager profiles and can be read with
`files("d810_egglog.baselines")` when running the extension's performance
checks.

The packaged profiles are the provider-owned activation fixtures. Use
`mba_portfolio_spike.json` for an interactive residual lane,
`mba_portfolio_deep.json` for bounded diagnostics, and
`mba_portfolio_telemetry_3ms.json` when measuring admission without invoking
the runtime. The remaining profiles are focused family, compiler-shape, and
native matcher experiments.

Core d810-ng remains usable without this optional distribution.
