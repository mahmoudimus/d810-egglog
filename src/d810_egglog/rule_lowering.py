"""Egglog rule declarations for admitted provider-neutral MBA rules.

The core repository owns rule admission and native certification.  This module
adapts admitted rules to the extension's typed-term catalogue.  Native capture,
rebuild, and proof remain behind the host facade; no native-AST compatibility
path is implemented here.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from d810.mba.extension_api import (
    CanonicalFixedBindings,
    AcMatchStopReason,
    CanonicalCompiledPattern,
    CanonicalPatternMalformed,
    CanonicalPatternUnsupported,
    CompiledMbaRule,
    TypedBvTerm,
    canonicalize_mba_term,
    compile_canonical_pattern,
    evaluate_frozen_constraints,
    match_canonical_term_pattern,
    require_admitted_compiled_rules,
    term_fingerprint,
)


@dataclass(frozen=True, slots=True)
class CanonicalMbaRuleCatalogueReport:
    """Facts collected while admitting one typed candidate.

    The matcher reports are deliberately retained as opaque portable records:
    callers can inspect actual comparisons, AC branch exploration, concrete
    bindings, and stop reasons without reconstructing telemetry from the
    number of accepted applications.
    """

    applications: tuple[tuple[CompiledMbaRule, TypedBvTerm, int], ...]
    comparisons: int
    commuted_branches: int
    fixed_binding_count: int
    matches: tuple[object, ...]
    stop_reasons: tuple[AcMatchStopReason, ...]

    @property
    def stop_reason(self) -> AcMatchStopReason | None:
        if AcMatchStopReason.COMPARISON_BUDGET in self.stop_reasons:
            return AcMatchStopReason.COMPARISON_BUDGET
        if AcMatchStopReason.MATCHED in self.stop_reasons:
            return AcMatchStopReason.MATCHED
        return self.stop_reasons[-1] if self.stop_reasons else None


@dataclass(frozen=True, slots=True)
class CanonicalMbaRuleCatalogue:
    """Extension-owned typed-term projection of admitted MBA rule templates.

    The native/POD catalogue remains in core.  This projection uses only the
    portable canonical-pattern primitives and is sufficient for Egglog's
    typed-term saturation path.
    """

    patterns: tuple[CanonicalCompiledPattern, ...]
    root_buckets: Mapping[tuple[str, int], tuple[CanonicalCompiledPattern, ...]]

    @classmethod
    def from_rules(
        cls, rules: tuple[CompiledMbaRule, ...]
    ) -> "CanonicalMbaRuleCatalogue":
        admitted_rules = require_admitted_compiled_rules(rules)
        compiled: list[CanonicalCompiledPattern] = []
        buckets: dict[tuple[str, int], list[CanonicalCompiledPattern]] = {}
        for declaration_index, rule in enumerate(admitted_rules):
            rule_patterns: list[CanonicalCompiledPattern] = []
            malformed = False
            for width in rule.proof_widths:
                try:
                    pattern = compile_canonical_pattern(
                        rule,
                        width=width,
                        declaration_index=declaration_index,
                    )
                except CanonicalPatternUnsupported:
                    continue
                except CanonicalPatternMalformed:
                    # A malformed declaration cannot enter the executable
                    # extension catalogue at any width.
                    malformed = True
                    break
                rule_patterns.append(pattern)
            if malformed:
                continue
            compiled.extend(rule_patterns)
            for pattern in rule_patterns:
                operation = pattern.pattern_term.operation
                if operation is not None:
                    buckets.setdefault((operation, pattern.width), []).append(pattern)
        return cls(
            tuple(compiled),
            MappingProxyType({key: tuple(value) for key, value in buckets.items()}),
        )

    def canonical_applications(
        self,
        candidate: TypedBvTerm,
        *,
        comparison_budget: int = 256,
    ) -> CanonicalMbaRuleCatalogueReport:
        if type(comparison_budget) is not int or comparison_budget <= 0:
            raise ValueError("comparison_budget must be a positive integer")
        if not isinstance(candidate, TypedBvTerm):
            raise TypeError("candidate must be a TypedBvTerm")
        canonical_candidate = canonicalize_mba_term(candidate).canonical_term
        operation = canonical_candidate.operation
        if operation is None:
            return CanonicalMbaRuleCatalogueReport((), 0, 0, 0, (), ())
        bucket = self.root_buckets.get((operation, canonical_candidate.width), ())
        if not bucket:
            return CanonicalMbaRuleCatalogueReport((), 0, 0, 0, (), ())

        applications: list[tuple[CompiledMbaRule, TypedBvTerm, int]] = []
        comparisons = 0
        commuted_branches = 0
        fixed_binding_count = 0
        matches: list[object] = []
        stop_reasons: list[AcMatchStopReason] = []
        seen: set[tuple[int, str]] = set()
        for pattern in bucket:
            remaining = comparison_budget - comparisons
            if remaining <= 0:
                stop_reasons.append(AcMatchStopReason.COMPARISON_BUDGET)
                break
            report = match_canonical_term_pattern(
                pattern,
                canonical_candidate,
                comparison_budget=remaining,
            )
            comparisons += report.comparisons
            commuted_branches += report.commuted_branches
            matches.extend(report.matches)
            fixed_binding_count += sum(
                len(getattr(getattr(match, "bindings", None), "terms", {}))
                for match in report.matches
            )
            stop_reasons.append(report.stop_reason)
            if report.stop_reason is AcMatchStopReason.COMPARISON_BUDGET:
                break
            for match in report.matches:
                bindings = dict(match.bindings.terms)
                if not evaluate_frozen_constraints(
                    pattern.constraints,
                    bindings,
                    width=canonical_candidate.width,
                ):
                    continue
                # Constraint evaluation may derive replacement-only values
                # (for example ``val_res``) that are intentionally absent
                # from the matcher's original binding object.  Materialize
                # from the validated derived mapping, while retaining the
                # matcher's raw candidate paths for native reconstruction.
                derived_bindings = CanonicalFixedBindings(
                    bindings,
                    match.bindings.candidate_paths,
                    match.bindings.width,
                )
                replacement = canonicalize_mba_term(
                    pattern.materialize_replacement(derived_bindings)
                ).canonical_term
                key = (id(pattern.rule), term_fingerprint(replacement))
                if key in seen:
                    continue
                seen.add(key)
                applications.append(
                    (pattern.rule, replacement, pattern.declaration_index)
                )
        return CanonicalMbaRuleCatalogueReport(
            tuple(applications),
            comparisons,
            commuted_branches,
            fixed_binding_count,
            tuple(matches),
            tuple(stop_reasons),
        )


def canonical_pattern_catalogue_for_rules(
    rules: Collection[object],
) -> CanonicalMbaRuleCatalogue:
    """Freeze one canonical catalogue for admitted Egglog rules.

    Structural rules use their extension-owned catalogue implementation.  DSL
    rules use the extension-owned typed-term catalogue.  The concrete
    native matcher remains in core for native/POD consumers. Mixed inputs are
    rejected so a caller cannot accidentally compare incompatible rule
    representations.
    """

    from .structural_rules import (
        CompiledEgglogStructuralRule,
        structural_catalogue_for_rules,
    )

    frozen_rules = tuple(rules)
    if frozen_rules and all(
        type(rule) is CompiledEgglogStructuralRule for rule in frozen_rules
    ):
        return structural_catalogue_for_rules(frozen_rules)
    if any(type(rule) is CompiledEgglogStructuralRule for rule in frozen_rules):
        raise ValueError("canonical catalogue cannot mix structural and DSL rules")

    return CanonicalMbaRuleCatalogue.from_rules(
        require_admitted_compiled_rules(frozen_rules)
    )


__all__ = [
    "CanonicalMbaRuleCatalogue",
    "CanonicalMbaRuleCatalogueReport",
    "CompiledMbaRule",
    "canonical_pattern_catalogue_for_rules",
]
