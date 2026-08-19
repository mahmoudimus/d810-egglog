"""Egglog-specific lowering receives only portable compiled MBA rules."""

from __future__ import annotations

import importlib


def test_rule_lowering_exports_egglog_catalogue_bridge_only() -> None:
    lowering = importlib.import_module("d810_egglog.rule_lowering")
    api = importlib.import_module("d810.mba.extension_api")

    assert lowering.CompiledMbaRule is api.CompiledMbaRule
    assert callable(lowering.canonical_pattern_catalogue_for_rules)
    assert not hasattr(lowering, "specialize")


def test_catalogue_materializes_replacement_from_derived_constraint_bindings() -> None:
    """Constraint-derived values must survive the Egglog catalogue boundary."""

    from d810.mba.certified_rule_compiler import compile_mba_rule_catalogue
    from d810.mba.typed_term import TypedBvTerm
    from d810_egglog.rule_lowering import CanonicalMbaRuleCatalogue

    rule = (
        compile_mba_rule_catalogue()
        .receipt_for("add", "Add_SpecialConstantRule_3")
        .compiled_rule
    )
    assert rule is not None

    x = TypedBvTerm(None, 32, leaf_key=("candidate", "x"))

    def constant(value):
        return TypedBvTerm(None, 32, value=value)

    def node(operation, *children):
        return TypedBvTerm(operation, 32, children=tuple(children))

    candidate = node(
        "add",
        node("xor", x, constant(-2)),
        node("mul", constant(2), node("or", x, constant(1))),
    )

    report = CanonicalMbaRuleCatalogue.from_rules((rule,)).canonical_applications(
        candidate,
        comparison_budget=64,
    )

    assert report.applications
    replacement = report.applications[0][1]
    assert replacement.operation == "add"
    assert any(child.leaf_key == ("candidate", "x") for child in replacement.children)
    assert any(child.value == 0 for child in replacement.children)
