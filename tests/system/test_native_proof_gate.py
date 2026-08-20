"""Native proof and structural-route acceptance for Egglog extraction."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

ida_hexrays = pytest.importorskip("ida_hexrays")
pytest.importorskip("egglog")

from d810.mba.provider_outcome import ProviderOutcomeStatus  # noqa: E402
from d810.mba.extension_api import compiled_rules_for_families  # noqa: E402
from d810.hexrays.expr import ast as ast_dispatcher  # noqa: E402
from d810.hexrays.ir.mop_snapshot import MopSnapshot  # noqa: E402
from d810_egglog.rules.egglog_optimizer import EgglogOptimizer  # noqa: E402
from tests.system.e2e.test_domain_lifted_semantic_simplification import (  # noqa: E402
    _native_fixed_shift_case,
    _native_semantic_instruction,
)


def _native_leaf(name: str, register: int):
    leaf = ast_dispatcher.AstLeaf(name)
    leaf.mop = MopSnapshot(t=ida_hexrays.mop_r, size=4, reg=register)
    leaf.dest_size = 4
    return leaf


def _native_degree_two_candidate():
    """Build the existing certified two-step bnot shape at the native AST layer."""

    left = ast_dispatcher.AstNode(
        ida_hexrays.m_bnot,
        _native_leaf("x", 1),
    )
    right = ast_dispatcher.AstNode(
        ida_hexrays.m_bnot,
        _native_leaf("y", 2),
    )
    left.dest_size = right.dest_size = 4
    candidate = ast_dispatcher.AstNode(ida_hexrays.m_xor, left, right)
    candidate.dest_size = 4
    return candidate


def test_native_degree_two_route_keeps_equal_cost_intermediate_then_reduces(
    copy_of_idb,
):
    """The real native host proves the two-step bnot route strictly smaller."""

    del copy_of_idb
    handler = EgglogOptimizer()
    handler.configure(
        {
            "families": ["bnot"],
            "max_leaves": 2,
            "max_operator_nodes": 10,
            "max_degree": 2,
            "saturation_rounds": 2,
            "max_eclasses": 256,
            "max_enodes": 512,
            "max_rule_firings": 32,
            "time_budget_ms": 1000,
            "require_proof": True,
        }
    )
    selected_rules = tuple(
        rule
        for rule in compiled_rules_for_families(("bnot",))
        if rule.source_name in {"BnotXor_FactorRule_1", "Bnot_FactorRule_5"}
    )
    assert len(selected_rules) == 2
    handler._catalogue = SimpleNamespace(compiled_rules=selected_rules)
    host = handler._host
    candidate = _native_degree_two_candidate()
    native_candidate = host.capture_ast(candidate, destination_size=4)
    extraction = handler._select_native_extraction(
        native_candidate.term,
        destination_size=4,
        profile=native_candidate.profile,
        initial_replacements={},
    )

    assert extraction.replacement_term is not None
    assert extraction.receipt.skip_reason is None
    assert extraction.receipt.degree == 2
    assert extraction.receipt.derivation_trace[:2] == (
        ("bnot", "BnotXor_FactorRule_1", ()),
        ("bnot", "Bnot_FactorRule_5", ()),
    )
    assert extraction.receipt.extracted_cost < extraction.receipt.input_cost
    reconstruction = host.rebuild_ast(native_candidate, extraction.replacement_term)
    assert reconstruction is not None
    assert host.prove_ast(
        native_candidate,
        reconstruction,
        certificate=None,
        known_constants=None,
    )


def test_native_nested_fixed_shifts_reduce_to_certified_rotate(copy_of_idb):
    """The nested native shift/or shape uses the fixed-rotate catalogue."""

    del copy_of_idb
    from d810.backends.mba.hexrays_island import lower_hexrays_island
    from d810_egglog.saturation import EgglogExtractionBudget, extract_bounded_term
    from d810_egglog.structural_rules import (
        compile_all_fixed_rotate_rules,
        structural_catalogue_for_rules,
    )

    candidate = _native_fixed_shift_case(
        ida_hexrays.m_or,
        count=7,
        root_or=True,
    )
    lowering = lower_hexrays_island(candidate, destination_size=4)
    assert lowering.term is not None
    assert lowering.term.operation == "or"
    assert {child.operation for child in lowering.term.children} == {"shl", "lshr"}
    rules = tuple(
        receipt.compiled_rule
        for receipt in compile_all_fixed_rotate_rules()
        if receipt.compiled_rule is not None
    )
    result = extract_bounded_term(
        lowering.raw_term,
        rules,
        EgglogExtractionBudget(
            max_leaves=2,
            max_operator_nodes=4,
            max_eclasses=128,
            max_enodes=256,
            time_budget_ms=1000,
        ),
        destination_size=4,
        profile=lowering.profile,
        catalogue=structural_catalogue_for_rules(rules),
    )

    assert result.replacement_term is not None
    assert result.replacement_term.operation == "rol"
    assert result.receipt.selected_family == "fixed_rotate"
    assert result.receipt.selected_source == "rol_32_7"
    assert result.receipt.degree == 1
    assert result.receipt.extracted_cost < result.receipt.input_cost


def test_native_proof_rejection_never_reports_applied(monkeypatch, copy_of_idb):
    """A real native proof refusal stops before mutation acceptance."""

    del copy_of_idb
    optimizer = EgglogOptimizer()
    optimizer.configure(
        {
            "families": ["xor"],
            "max_leaves": 2,
            "max_operator_nodes": 16,
            "max_degree": 1,
            "saturation_rounds": 1,
            "max_eclasses": 128,
            "max_enodes": 256,
            "max_rule_firings": 32,
            "time_budget_ms": 1000,
            "require_proof": True,
        }
    )
    optimizer._direct_native_application = lambda **_kwargs: None
    monkeypatch.setattr(
        optimizer._host,
        "prove",
        lambda *_args, **_kwargs: False,
        raising=False,
    )
    optimizer.begin_provider_outcome_capture()
    try:
        assert (
            optimizer._check_and_replace(_native_semantic_instruction(), blk=None)
            is None
        )
        receipt = optimizer.last_extraction_receipt
        assert receipt is not None
        assert receipt.skip_reason.value == "proof_failed"
        outcome = optimizer.provider_outcomes()[-1]
        assert outcome.status is ProviderOutcomeStatus.PROOF_FAILED
        optimizer.record_mutation_accepted()
        assert (
            optimizer.provider_outcomes()[-1].status
            is ProviderOutcomeStatus.PROOF_FAILED
        )
    finally:
        optimizer.end_provider_outcome_capture()
