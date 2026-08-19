"""Proof-gated fixed-rotate rules owned by the Egglog extension."""

from __future__ import annotations

import importlib


def test_structural_rule_catalogue_builds_typed_rotate_identity() -> None:
    structural = importlib.import_module("d810_egglog.structural_rules")

    pattern, replacement = structural.build_rotate_identity(8, "rol", 3)

    assert pattern.operation == "or"
    assert replacement.operation == "rol"
    assert replacement.shift_count == 3


def test_structural_rule_receipt_is_extension_owned() -> None:
    structural = importlib.import_module("d810_egglog.structural_rules")

    assert structural.StructuralRuleStatus.COMPILED.value == "compiled"
    assert structural.CompiledEgglogStructuralRule.__module__ == structural.__name__
