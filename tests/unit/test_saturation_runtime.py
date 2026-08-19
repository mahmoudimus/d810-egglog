"""Typed-term Egglog runtime tests split from the core saturation suite."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from d810_egglog import saturation
from d810_egglog.rule_lowering import (
    CanonicalMbaRuleCatalogue,
    canonical_pattern_catalogue_for_rules,
)
from d810_egglog.structural_rules import (
    compile_all_fixed_rotate_rules,
    structural_catalogue_for_rules,
)
from d810.mba import typed_term
from d810.mba.extension_api import (
    CanonicalPatternComparisonBudgetExceeded,
    TypedBvTerm,
)
from d810.mba.egraph_contracts import EgraphExtractionReceipt, EgraphSkipReason
from d810.mba.island_profile import MbaIslandClass, MbaIslandProfile
from d810.mba.differential_report import egraph_receipt_to_outcome


def _leaf(name: str, *, width: int = 32) -> TypedBvTerm:
    return TypedBvTerm(None, width, leaf_key=("register", name))


def _constant(value: int, *, width: int = 32) -> TypedBvTerm:
    return TypedBvTerm(None, width, value=value)


def _node(
    operation: str,
    left: TypedBvTerm,
    right: TypedBvTerm | None = None,
    *,
    width: int = 32,
) -> TypedBvTerm:
    children = (left,) if right is None else (left, right)
    return TypedBvTerm(operation, width, children=children)


def _fixed_shift(operation: str, value: TypedBvTerm, count: int) -> TypedBvTerm:
    return TypedBvTerm(
        operation,
        value.width,
        children=(value,),
        shift_count=count,
    )


def test_saturation_uses_the_portable_receipt_contract() -> None:
    profile = MbaIslandProfile(
        width_bits=32,
        operator_count=1,
        total_node_count=1,
        distinct_leaf_count=1,
        constant_count=0,
        operations=(("add", 1),),
        has_boolean=False,
        has_arithmetic=True,
        nonlinear_product_count=0,
        island_class=MbaIslandClass.LINEAR_MBA,
        blockers=(),
        fingerprint="portable-contract",
    )
    receipt = saturation.extraction_receipt_for_profile(
        profile,
        EgraphSkipReason.CANDIDATE_BUDGET,
    )
    assert type(receipt) is EgraphExtractionReceipt
    assert type(receipt.skip_reason) is EgraphSkipReason


def test_extension_catalogue_matches_admitted_canonical_rules_in_order() -> None:
    from d810.mba.certified_rule_compiler import compile_add_rule_catalogue

    rules = compile_add_rule_catalogue().compiled_rules
    assert rules
    catalogue = CanonicalMbaRuleCatalogue.from_rules(rules)
    source = catalogue.patterns[0].pattern_term

    applications = catalogue.canonical_applications(source, comparison_budget=256)

    assert applications
    assert applications[0][0] is rules[0]
    assert applications[0][2] == 0


def test_extension_catalogue_fails_closed_on_comparison_budget() -> None:
    from d810.mba.certified_rule_compiler import compile_add_rule_catalogue

    rule = compile_add_rule_catalogue().compiled_rules[0]
    catalogue = CanonicalMbaRuleCatalogue.from_rules((rule,))
    source = catalogue.patterns[0].pattern_term

    with pytest.raises(CanonicalPatternComparisonBudgetExceeded):
        catalogue.canonical_applications(source, comparison_budget=1)


def test_extension_catalogue_matches_core_canonical_oracle() -> None:
    """Differentially pin order, constraints, deduplication, and budget semantics."""

    from d810.backends.mba.compiled_pattern_catalogue import (
        CompiledPatternCatalogue,
    )
    from d810.mba.certified_rule_compiler import compile_add_rule_catalogue

    rules = compile_add_rule_catalogue().compiled_rules
    extension_catalogue = CanonicalMbaRuleCatalogue.from_rules(rules)
    core_catalogue = CompiledPatternCatalogue.from_rules(rules)
    candidate = extension_catalogue.patterns[0].pattern_term

    extension_result = extension_catalogue.canonical_applications(
        candidate,
        comparison_budget=256,
    )
    core_result = core_catalogue.canonical_applications(
        candidate,
        comparison_budget=256,
    )
    assert [
        (rule.source_name, replacement, index)
        for rule, replacement, index in extension_result
    ] == [
        (rule.source_name, replacement, index)
        for rule, replacement, index in core_result
    ]

    constrained_rule = next(rule for rule in rules if rule.constraints)
    assert constrained_rule.source_name == "Add_SpecialConstantRule_1"
    constrained_extension = CanonicalMbaRuleCatalogue.from_rules(
        (constrained_rule,)
    )
    constrained_core = CompiledPatternCatalogue.from_rules((constrained_rule,))
    x = _leaf("constraint-x")
    satisfying = _node(
        "add",
        _node("xor", x, _constant(0x55)),
        _node("mul", _constant(2), _node("and", x, _constant(0x55))),
    )
    failing = _node(
        "add",
        _node("xor", x, _constant(0x55)),
        _node("mul", _constant(2), _node("and", x, _constant(0xAA))),
    )

    def project(result):
        return [
            (rule.source_name, replacement, index)
            for rule, replacement, index in result
        ]

    assert project(
        constrained_extension.canonical_applications(
            satisfying,
            comparison_budget=256,
        )
    ) == project(
        constrained_core.canonical_applications(
            satisfying,
            comparison_budget=256,
        )
    )
    assert project(
        constrained_extension.canonical_applications(
            failing,
            comparison_budget=256,
        )
    ) == project(
        constrained_core.canonical_applications(
            failing,
            comparison_budget=256,
        )
    ) == []

    duplicate_extension = CanonicalMbaRuleCatalogue.from_rules((rules[0], rules[0]))
    duplicate_core = CompiledPatternCatalogue.from_rules((rules[0], rules[0]))
    duplicate_candidate = duplicate_extension.patterns[0].pattern_term
    assert [
        (rule.source_name, replacement, index)
        for rule, replacement, index in duplicate_extension.canonical_applications(
            duplicate_candidate,
            comparison_budget=256,
        )
    ] == [
        (rule.source_name, replacement, index)
        for rule, replacement, index in duplicate_core.canonical_applications(
            duplicate_candidate,
            comparison_budget=256,
        )
    ]

    with pytest.raises(CanonicalPatternComparisonBudgetExceeded):
        extension_catalogue.canonical_applications(candidate, comparison_budget=1)
    with pytest.raises(CanonicalPatternComparisonBudgetExceeded):
        core_catalogue.canonical_applications(candidate, comparison_budget=1)


def test_extension_catalogue_matches_core_unsupported_and_malformed_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from d810.mba.certified_rule_compiler import compile_add_rule_catalogue
    from d810_egglog import rule_lowering

    rule = compile_add_rule_catalogue().compiled_rules[0]
    original_compile = rule_lowering.compile_canonical_pattern

    def skip_one_width(rule, *, width, declaration_index):
        if width == 16:
            raise rule_lowering.CanonicalPatternUnsupported("test unsupported width")
        return original_compile(rule, width=width, declaration_index=declaration_index)

    monkeypatch.setattr(rule_lowering, "compile_canonical_pattern", skip_one_width)
    extension_catalogue = CanonicalMbaRuleCatalogue.from_rules((rule,))
    assert tuple(pattern.width for pattern in extension_catalogue.patterns) == (
        8,
        32,
        64,
    )

    def reject_one_width(rule, *, width, declaration_index):
        if width == 16:
            raise rule_lowering.CanonicalPatternMalformed("test malformed width")
        return original_compile(rule, width=width, declaration_index=declaration_index)

    monkeypatch.setattr(rule_lowering, "compile_canonical_pattern", reject_one_width)
    assert CanonicalMbaRuleCatalogue.from_rules((rule,)).patterns == ()


def test_extension_catalogue_bridge_rejects_unadmitted_rules() -> None:
    with pytest.raises(ValueError, match="admitted"):
        canonical_pattern_catalogue_for_rules((object(),))


def test_structural_catalogue_remains_extension_owned() -> None:
    rules = tuple(
        receipt.compiled_rule
        for receipt in compile_all_fixed_rotate_rules()
        if receipt.compiled_rule is not None
    )
    assert len(rules) == 232
    catalogue = structural_catalogue_for_rules(rules)
    x = _leaf("x", width=64)
    source = _node(
        "or",
        _fixed_shift("shl", x, 31),
        _fixed_shift("lshr", x, 33),
        width=64,
    )

    applications = catalogue.canonical_applications(source, comparison_budget=256)

    assert len(applications) == 1
    selected_rule, replacement, _index = applications[0]
    assert selected_rule.source_name == "rol_64_31"
    assert selected_rule.aliases == ("ror_64_33",)
    assert replacement == _fixed_shift("rol", x, 31)


def test_fixed_shift_serialization_keeps_literal_count_in_constructor(monkeypatch):
    calls: list[tuple[object, ...]] = []

    class BvExpr:
        @classmethod
        def leaf(cls, width, key):
            return ("leaf", width, key)

        @classmethod
        def constant(cls, width, value):
            return ("constant", width, value)

        @classmethod
        def unary(cls, operation, width, operand):
            return ("unary", operation, width, operand)

        @classmethod
        def binary(cls, operation, width, left, right):
            return ("binary", operation, width, left, right)

        @classmethod
        def fixed_shift(cls, operation, width, count, operand):
            calls.append((operation, width, count, operand))
            return ("fixed_shift", operation, width, count, operand)

    monkeypatch.setattr(saturation, "BvExpr", BvExpr)
    lowered = saturation._term_to_egglog(_fixed_shift("rol", _leaf("x"), 5))

    assert calls[0][:3] == ("rol", 32, 5)
    assert calls[0][3][:2] == ("leaf", 32)
    assert lowered[:4] == ("fixed_shift", "rol", 32, 5)


def test_canonicalization_and_function_budget_are_provider_neutral() -> None:
    a, b, c = _leaf("a"), _leaf("b"), _leaf("c")
    left = _node("add", _node("add", a, b), c)
    right = _node("add", a, _node("add", c, b))
    assert saturation.canonicalize_ac_term(left) == saturation.canonicalize_ac_term(right)
    assert saturation.canonicalize_ac_term(_node("sub", a, b)) != saturation.canonicalize_ac_term(
        _node("sub", b, a)
    )

    budget = saturation.EgglogFunctionBudget(1_000)
    assert budget.remaining_ms((0x401000, 101), now=10.0) == 1_000
    assert budget.remaining_ms((0x401000, 101), now=10.250) == 750
    assert budget.remaining_ms((0x401000, 202), now=20.0) == 1_000


def test_typed_term_and_receipt_contracts_are_immutable() -> None:
    assert _constant(0x1FF, width=8).value == 0xFF
    budget = saturation.EgglogExtractionBudget()
    receipt = EgraphExtractionReceipt()
    with pytest.raises(FrozenInstanceError):
        budget.max_degree = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        receipt.degree = 1  # type: ignore[misc]


def test_run_count_appears_only_after_actual_egglog_invocation(monkeypatch) -> None:
    raw = _node("add", _leaf("x"), _constant(0))
    rule = SimpleNamespace(family="test", source_name="identity", aliases=())
    replacement = _leaf("x")
    catalogue = SimpleNamespace(
        canonical_applications=lambda _term, comparison_budget: ((rule, replacement, 0),)
    )
    rewrite_decl = object()
    run_calls: list[int] = []

    class EGraph:
        def register(self, *_commands):
            return None

        def run(self, _rounds):
            run_calls.append(1)
            return SimpleNamespace(
                num_matches_per_rule={rewrite_decl: 1},
                updated=False,
            )

        def extract(self, _expression):
            return (0, 1)

    monkeypatch.setattr(
        saturation,
        "_load_egglog_module",
        lambda: SimpleNamespace(
            EGraph=EGraph,
            EggSmolError=RuntimeError,
            rewrite=lambda _source: SimpleNamespace(
                to=lambda _target: SimpleNamespace(decl=rewrite_decl)
            ),
        ),
    )
    monkeypatch.setattr(saturation, "read_egraph_statistics", lambda _egraph: (1, 1))
    monkeypatch.setattr(saturation, "release_egraph_on_owner_thread", lambda _egraph: True)

    result = saturation.extract_bounded_term(
        raw,
        (rule,),
        saturation.EgglogExtractionBudget(time_budget_ms=1_000),
        destination_size=4,
        catalogue=catalogue,
    )
    assert result.replacement_term == replacement
    assert run_calls == [1]
    assert result.receipt.egraph_run_count == 1

    telemetry = saturation.extract_bounded_term(
        raw,
        (rule,),
        saturation.EgglogExtractionBudget(),
        destination_size=4,
        catalogue=catalogue,
    )
    assert telemetry.receipt.egraph_run_count is None


def test_canonicalization_only_shrinkage_is_not_a_rewrite(monkeypatch) -> None:
    raw = _node("neg", _node("neg", _leaf("x")))
    canonical = saturation.canonicalize_mba_term(raw).canonical_term
    assert canonical == _leaf("x")

    rule = SimpleNamespace(family="test", source_name="identity", aliases=())
    catalogue = SimpleNamespace(
        canonical_applications=lambda _term, comparison_budget: ((rule, canonical, 0),)
    )
    rewrite_decl = object()

    class EGraph:
        def register(self, *_commands):
            return None

        def run(self, _rounds):
            return SimpleNamespace(num_matches_per_rule={rewrite_decl: 1}, updated=False)

        def extract(self, _expression):
            return (0, 1)

    monkeypatch.setattr(
        saturation,
        "_load_egglog_module",
        lambda: SimpleNamespace(
            EGraph=EGraph,
            EggSmolError=RuntimeError,
            rewrite=lambda _source: SimpleNamespace(
                to=lambda _target: SimpleNamespace(decl=rewrite_decl)
            ),
        ),
    )
    monkeypatch.setattr(saturation, "read_egraph_statistics", lambda _egraph: (1, 1))
    monkeypatch.setattr(saturation, "release_egraph_on_owner_thread", lambda _egraph: True)

    result = saturation.extract_bounded_term(
        raw,
        (rule,),
        saturation.EgglogExtractionBudget(time_budget_ms=1_000),
        destination_size=4,
        catalogue=catalogue,
    )
    assert result.replacement_term is None
    assert result.receipt.skip_reason is EgraphSkipReason.NON_MBA_CANDIDATE
    assert result.receipt.input_cost == typed_term.term_cost(raw)


def test_receipt_outcome_keeps_replay_telemetry() -> None:
    trace = (("xor", "rule", ()),)
    receipt = EgraphExtractionReceipt(
        input_cost=(5, 8),
        extracted_cost=(2, 3),
        execution_path="learned_replay",
        cache_status="hit",
        cache_key='["catalogue"]',
        replayed_trace=trace,
        cache_lookup_elapsed_ms=0.25,
        replay_rebuild_elapsed_ms=0.75,
        replay_proof_elapsed_ms=1.25,
        egraph_work_units=0,
        egraph_run_count=0,
        derivation_trace=trace,
    )
    outcome = egraph_receipt_to_outcome(receipt)
    assert outcome.metadata["execution_path"] == "learned_replay"
    assert outcome.metadata["egraph_run_count"] == 0
