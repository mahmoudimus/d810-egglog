"""Optional Egglog backend manifest for d810-ng.

The package root is intentionally a cheap declaration surface.  D810 resolves
the runtime and rule modules named here only after it has selected this
backend, so importing the manifest never imports Egglog, IDA, or the optimizer.
"""

from __future__ import annotations

__version__ = "0.1.0"

MANIFEST = {
    "name": "egglog",
    "api_version": 1,
    "provides": "d810_egglog.runtime",
    "rules": ("d810_egglog.rules.egglog_optimizer",),
    "implements": {"mba-egraph": "EgglogOptimizer"},
}

__all__ = ["MANIFEST", "__version__"]
