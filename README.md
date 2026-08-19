# d810-egglog

`d810-egglog` is the optional Egglog implementation of d810-ng's
backend-neutral `mba-egraph` pass.  Installing this distribution registers the
`egglog` backend through the `d810.backends` entry-point group.

The package currently contains the lightweight manifest and runtime probe. The
optimizer and its declared rule module are added by the subsequent extraction
tasks. The probe accepts the audited Egglog 13.2.0 runtime and reports an
actionable reason when the optional runtime is absent or cannot be imported.

Install it alongside d810-ng when the e-graph backend is needed:

```bash
python -m pip install d810-egglog
```

Core d810-ng remains usable without this optional distribution.
