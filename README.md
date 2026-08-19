# d810-egglog

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
the hard-cut `mba-egraph` pass; the old `mba-egglog` spelling is not accepted.

Core d810-ng remains usable without this optional distribution.
