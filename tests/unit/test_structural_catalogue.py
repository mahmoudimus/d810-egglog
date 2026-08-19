from __future__ import annotations

import pytest

from d810.mba.typed_term import TypedBvTerm, fixed_shift_term


def test_fixed_rotate_structural_catalogue_certifies_every_nonzero_count():
    from d810_egglog.structural_rules import (
        StructuralRuleStatus,
        compile_fixed_rotate_rules,
    )

    for width in (8, 16, 32, 64):
        for direction in ("rol", "ror"):
            receipts = compile_fixed_rotate_rules(width=width, direction=direction)
            assert len(receipts) == width - 1
            assert all(
                receipt.status is StructuralRuleStatus.COMPILED
                for receipt in receipts
            )
            assert all(receipt.proof_verdict is True for receipt in receipts)
            assert tuple(receipt.count for receipt in receipts) == tuple(
                range(1, width)
            )


def test_fixed_rotate_structural_receipts_are_frozen_and_wire_stable():
    from dataclasses import FrozenInstanceError

    from d810_egglog.structural_rules import (
        StructuralRuleCompilationReceipt,
        StructuralRuleStatus,
        compile_fixed_rotate_rules,
    )

    receipt = compile_fixed_rotate_rules(width=8, direction="rol")[0]
    assert isinstance(receipt, StructuralRuleCompilationReceipt)
    assert receipt.to_dict() == {
        "source_name": "rol_8_1",
        "status": StructuralRuleStatus.COMPILED.value,
        "width": 8,
        "direction": "rol",
        "count": 1,
        "proof_verdict": True,
        "refusal_reason": None,
    }
    with pytest.raises(FrozenInstanceError):
        receipt.count = 2  # type: ignore[misc]


def test_failed_fixed_rotate_certification_omits_only_that_rule(monkeypatch):
    from d810.mba import extension_api
    from d810_egglog import structural_rules as egglog_structural_rules
    from d810_egglog.structural_rules import StructuralRuleStatus

    original = extension_api.enroll_structural_rule

    def reject_count_three(rule):
        if rule.count == 3:
            raise ValueError("test proof failure")
        return original(rule)

    monkeypatch.setattr(extension_api, "enroll_structural_rule", reject_count_three)
    receipts = egglog_structural_rules.compile_fixed_rotate_rules(
        width=8, direction="rol"
    )

    rejected = receipts[2]
    assert rejected.count == 3
    assert rejected.status is StructuralRuleStatus.REJECTED
    assert rejected.compiled_rule is None
    assert rejected.refusal_reason == "typed_z3_proof_failed"
    assert sum(item.compiled_rule is not None for item in receipts) == 6


def test_fixed_rotate_compiles_once_per_rule_through_public_enrollment(monkeypatch):
    from d810.mba import extension_api
    from d810_egglog import structural_rules as egglog_structural_rules

    original_enroll = extension_api.enroll_structural_rule
    original_proof = extension_api.prove_typed_term_equivalence
    enrollment_calls: list[str] = []
    api_proof_calls = 0
    provider_proof_calls = 0

    def enroll_once(rule):
        enrollment_calls.append(rule.source_name)
        return original_enroll(rule)

    def count_api_proof(pattern, replacement):
        nonlocal api_proof_calls
        api_proof_calls += 1
        return original_proof(pattern, replacement)

    def count_provider_proof(pattern, replacement):
        nonlocal provider_proof_calls
        provider_proof_calls += 1
        return original_proof(pattern, replacement)

    monkeypatch.setattr(extension_api, "enroll_structural_rule", enroll_once)
    monkeypatch.setattr(extension_api, "prove_typed_term_equivalence", count_api_proof)
    monkeypatch.setattr(
        egglog_structural_rules,
        "_prove_typed_term_equivalence",
        count_provider_proof,
        raising=False,
    )
    receipts = egglog_structural_rules.compile_fixed_rotate_rules(
        width=8, direction="rol"
    )

    assert len(receipts) == 7
    assert enrollment_calls == [f"rol_8_{count}" for count in range(1, 8)]
    assert api_proof_calls == 7
    assert provider_proof_calls == 0


@pytest.mark.parametrize("direction", ["rol", "ror"])
def test_fixed_rotate_rejects_invalid_width_direction_and_count(direction):
    from d810_egglog.structural_rules import (
        build_rotate_identity,
        compile_fixed_rotate_rules,
    )

    with pytest.raises(ValueError, match="width"):
        compile_fixed_rotate_rules(width=24, direction=direction)
    with pytest.raises(ValueError, match="direction"):
        compile_fixed_rotate_rules(width=8, direction="bad")
    with pytest.raises(ValueError, match="count"):
        build_rotate_identity(8, direction, 0)
    with pytest.raises(ValueError, match="count"):
        build_rotate_identity(8, direction, 8)


def test_fixed_rotate_rejects_signed_mixed_width_and_extra_operand_shapes():
    from d810_egglog.structural_rules import (
        compile_fixed_rotate_rules,
        structural_catalogue_for_rules,
    )

    rule = compile_fixed_rotate_rules(width=32, direction="rol")[4].compiled_rule
    assert rule is not None
    catalogue = structural_catalogue_for_rules((rule,))
    x32 = TypedBvTerm(None, 32, leaf_key=("register", "x"))

    # Arithmetic shifts are deliberately outside the typed fixed-shift
    # vocabulary, so they cannot enter the structural catalogue at all.
    with pytest.raises(ValueError, match="shift_count"):
        fixed_shift_term("sar", 32, x32, 5)

    # A source at another width cannot match a 32-bit certified rule.
    x16 = TypedBvTerm(None, 16, leaf_key=("register", "x"))
    mixed_width_candidate = TypedBvTerm(
        "or",
        16,
        children=(
            fixed_shift_term("shl", 16, x16, 5),
            fixed_shift_term("lshr", 16, x16, 11),
        ),
    )
    assert catalogue.canonical_applications(mixed_width_candidate) == ()
    with pytest.raises(ValueError, match="same width"):
        TypedBvTerm(
            "or",
            32,
            children=(
                fixed_shift_term("shl", 32, x32, 5),
                fixed_shift_term("lshr", 16, x16, 11),
            ),
        )

    # An enclosing operand changes the root shape and must not be searched
    # through by the candidate-root-only structural route.
    source = TypedBvTerm(
        "or",
        32,
        children=(
            fixed_shift_term("shl", 32, x32, 5),
            fixed_shift_term("lshr", 32, x32, 27),
        ),
    )
    extra_operand = TypedBvTerm(
        "add",
        32,
        children=(TypedBvTerm(None, 32, value=0), source),
    )
    assert catalogue.canonical_applications(extra_operand) == ()


def test_snapshot_fingerprint_binds_admitted_structural_rotate_inventory():
    from d810_egglog.structural_rules import compile_fixed_rotate_rules
    from d810.mba.certified_catalogue import build_certified_catalogue_snapshot

    receipts = compile_fixed_rotate_rules(width=8, direction="rol")
    structural_rules = tuple(
        receipt.compiled_rule
        for receipt in receipts
        if receipt.compiled_rule is not None
    )
    complete = build_certified_catalogue_snapshot(
        (),
        compiler_version="structural-v1",
        widths=(8,),
        structural_rules=structural_rules,
    )
    incomplete = build_certified_catalogue_snapshot(
        (),
        compiler_version="structural-v1",
        widths=(8,),
        structural_rules=structural_rules[:-1],
    )

    assert complete.structural_rule_fingerprints
    assert complete.structural_rule_digest
    assert complete.fingerprint != incomplete.fingerprint
    assert complete.structural_rule_digest != incomplete.structural_rule_digest


def test_snapshot_rejects_forged_structural_rule_with_imported_token():
    from d810.mba.certified_catalogue import (
        _STRUCTURAL_RULE_ADMISSION_TOKEN,
        build_certified_catalogue_snapshot,
    )

    class ForgedStructuralRule:
        source_name = "rol_32_5"
        width = 32
        direction = "rol"
        count = 5
        proof_verdict = True
        family = "fixed_rotate"
        semantic_fingerprint = "forged-rotate-fingerprint"

    forged = ForgedStructuralRule()
    forged._admission_token = _STRUCTURAL_RULE_ADMISSION_TOKEN
    unmarked = ForgedStructuralRule()
    forged_snapshot = build_certified_catalogue_snapshot(
        (),
        compiler_version="structural-v1",
        structural_rules=(forged,),
    )
    unavailable_snapshot = build_certified_catalogue_snapshot(
        (),
        compiler_version="structural-v1",
        structural_rules=(unmarked,),
    )

    assert forged_snapshot.structural_authorizable is False
    assert forged_snapshot.structural_rule_fingerprints == ()
    assert (
        forged_snapshot.structural_rule_digest
        == unavailable_snapshot.structural_rule_digest
    )


def test_public_enrollment_rejects_forged_structural_equivalence():
    from d810.mba.extension_api import (
        enroll_structural_rule,
        is_enrolled_structural_rule,
    )
    from d810_egglog.structural_rules import (
        CompiledEgglogStructuralRule,
        build_rotate_identity,
        structural_catalogue_for_rules,
    )

    pattern, _replacement = build_rotate_identity(8, "rol", 1)
    x = pattern.children[0].children[0]
    forged = CompiledEgglogStructuralRule(
        source_name="forged-rol-8-1",
        width=8,
        direction="rol",
        count=1,
        pattern=pattern,
        replacement=fixed_shift_term("ror", 8, x, 1),
        proof_verdict=True,
    )

    with pytest.raises(ValueError, match="structural rule"):
        enroll_structural_rule(forged)
    assert not is_enrolled_structural_rule(forged)
    with pytest.raises(ValueError, match="admitted"):
        structural_catalogue_for_rules((forged,))


def test_structural_fingerprint_delegates_to_portable_api(monkeypatch):
    from d810.mba import extension_api
    from d810_egglog.structural_rules import compile_fixed_rotate_rules

    rule = compile_fixed_rotate_rules(width=8, direction="rol")[0].compiled_rule
    assert rule is not None
    monkeypatch.setattr(
        extension_api,
        "structural_rule_semantic_fingerprint",
        lambda _rule: "portable-fingerprint",
    )

    assert rule.semantic_fingerprint == "portable-fingerprint"


def test_alias_enrollment_reuses_proof_for_each_unique_identity(monkeypatch):
    from d810.mba import extension_api
    from d810_egglog.structural_rules import (
        compile_fixed_rotate_rules,
        structural_catalogue_for_rules,
    )

    declarations = (
        compile_fixed_rotate_rules(width=8, direction="rol")[0],
        compile_fixed_rotate_rules(width=8, direction="ror")[-1],
    )
    rules = tuple(
        receipt.compiled_rule
        for receipt in declarations
        if receipt.compiled_rule is not None
    )
    original_proof = extension_api.prove_typed_term_equivalence
    proof_calls = 0

    def count_proofs(pattern, replacement):
        nonlocal proof_calls
        proof_calls += 1
        return original_proof(pattern, replacement)

    monkeypatch.setattr(extension_api, "prove_typed_term_equivalence", count_proofs)
    for rule in rules:
        extension_api.enroll_structural_rule(rule)
    structural_catalogue_for_rules(rules)

    assert proof_calls == len(rules)


def test_changed_proof_function_forces_alias_reproof(monkeypatch):
    from d810.mba import extension_api
    from d810_egglog.structural_rules import (
        compile_fixed_rotate_rules,
        structural_catalogue_for_rules,
    )

    rule = compile_fixed_rotate_rules(width=8, direction="rol")[0].compiled_rule
    assert rule is not None
    paired = compile_fixed_rotate_rules(width=8, direction="ror")[-1].compiled_rule
    assert paired is not None
    original_proof = extension_api.prove_typed_term_equivalence
    first_calls = 0
    second_calls = 0

    def first_proof(pattern, replacement):
        nonlocal first_calls
        first_calls += 1
        return original_proof(pattern, replacement)

    def second_proof(pattern, replacement):
        nonlocal second_calls
        second_calls += 1
        return original_proof(pattern, replacement)

    monkeypatch.setattr(extension_api, "prove_typed_term_equivalence", first_proof)
    structural_catalogue_for_rules((rule, paired))
    monkeypatch.setattr(extension_api, "prove_typed_term_equivalence", second_proof)
    structural_catalogue_for_rules((rule, paired))

    assert first_calls == 1
    assert second_calls == 1


def test_public_enrollment_rejects_equivalent_duck_with_dishonest_fingerprint(
    monkeypatch,
):
    from d810.mba import extension_api
    from d810.mba.certified_catalogue import build_certified_catalogue_snapshot
    from d810_egglog.structural_rules import build_rotate_identity

    pattern, replacement = build_rotate_identity(8, "rol", 1)

    class EquivalentDuck:
        source_name = "duck-rol-8-1"
        width = 8
        direction = "rol"
        count = 1
        family = "fixed_rotate"
        aliases = ("duck-alias",)
        proof_widths = (8,)
        proof_verdict = True
        semantic_fingerprint = "dishonest-fingerprint"

        def __init__(self):
            self.pattern = pattern
            self.replacement = replacement

    proof_calls = 0

    def unexpected_proof(_pattern, _replacement):
        nonlocal proof_calls
        proof_calls += 1
        return True

    monkeypatch.setattr(
        extension_api, "prove_typed_term_equivalence", unexpected_proof
    )
    forged = EquivalentDuck()

    with pytest.raises(ValueError, match="fingerprint"):
        extension_api.enroll_structural_rule(forged)
    assert proof_calls == 0
    snapshot = build_certified_catalogue_snapshot(
        (), compiler_version="forged-duck", structural_rules=(forged,)
    )
    assert snapshot.structural_authorizable is False
    assert snapshot.structural_rule_fingerprints == ()


def test_mutating_enrolled_duck_invalidates_structural_authorization(monkeypatch):
    from d810.mba import extension_api
    from d810.mba.certified_catalogue import build_certified_catalogue_snapshot
    from d810_egglog.structural_rules import build_rotate_identity

    class MutableDuck:
        source_name = "mutable-rotate"
        width = 8
        direction = "rol"
        count = 1
        family = "fixed_rotate"
        aliases = ()
        proof_widths = (8,)
        proof_verdict = True

    pattern, replacement = build_rotate_identity(8, "rol", 1)
    duck = MutableDuck()
    duck.pattern = pattern
    duck.replacement = replacement
    duck.semantic_fingerprint = extension_api.structural_rule_semantic_fingerprint(
        duck
    )
    monkeypatch.setattr(
        extension_api, "prove_typed_term_equivalence", lambda *_terms: True
    )

    extension_api.enroll_structural_rule(duck)
    assert extension_api.is_enrolled_structural_rule(duck)

    duck.aliases = ("mutated-alias",)
    assert not extension_api.is_enrolled_structural_rule(duck)
    duck.aliases = ()
    extension_api.enroll_structural_rule(duck)

    duck.semantic_fingerprint = "tampered-fingerprint"
    assert not extension_api.is_enrolled_structural_rule(duck)
    duck.semantic_fingerprint = extension_api.structural_rule_semantic_fingerprint(
        duck
    )
    extension_api.enroll_structural_rule(duck)

    duck.direction = "ror"
    duck.count = 2
    duck.pattern, duck.replacement = build_rotate_identity(8, "ror", 2)
    duck.semantic_fingerprint = extension_api.structural_rule_semantic_fingerprint(
        duck
    )

    assert not extension_api.is_enrolled_structural_rule(duck)
    snapshot = build_certified_catalogue_snapshot(
        (), compiler_version="mutated-duck", structural_rules=(duck,)
    )
    assert snapshot.structural_authorizable is False
    assert snapshot.structural_rule_fingerprints == ()


def test_fixed_rotate_inventory_reuses_certification_across_live_requests(monkeypatch):
    from d810_egglog import structural_rules as egglog_structural_rules

    compile_all = egglog_structural_rules.compile_all_fixed_rotate_rules
    compile_all.cache_clear()
    first = compile_all()
    calls = 0

    def unexpected_reproof(pattern, replacement):
        nonlocal calls
        calls += 1
        raise AssertionError("cached fixed-rotate inventory re-entered proof gate")

    monkeypatch.setattr(
        egglog_structural_rules,
        "prove_typed_term_equivalence",
        unexpected_reproof,
    )
    try:
        second = compile_all()
    finally:
        compile_all.cache_clear()

    assert second is first
    assert calls == 0
