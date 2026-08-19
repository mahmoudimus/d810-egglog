"""Egglog-specific lowering receives only portable compiled MBA rules."""

from __future__ import annotations

import importlib


def test_rule_lowering_exports_egglog_catalogue_bridge_only() -> None:
    lowering = importlib.import_module("d810_egglog.rule_lowering")
    api = importlib.import_module("d810.mba.extension_api")

    assert lowering.CompiledMbaRule is api.CompiledMbaRule
    assert callable(lowering.canonical_pattern_catalogue_for_rules)
    assert not hasattr(lowering, "specialize")
