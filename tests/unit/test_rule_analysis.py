"""Tests for the extension-owned Egglog rule relationship analysis."""

from __future__ import annotations

from d810_egglog import rule_analysis


def test_symbolic_expression_conversion_preserves_shared_variables() -> None:
    from d810.mba.dsl import Var

    x = Var("x_0")
    cache: dict[str, object] = {}

    result = rule_analysis._symbolic_expr_to_pattern_expr(x + x, cache)

    assert result is not None
    assert tuple(cache) == ("x_0",)


def test_pattern_equivalence_uses_extension_owned_egglog_type() -> None:
    x = rule_analysis.PatternExpr.var("x")
    y = rule_analysis.PatternExpr.var("y")

    assert rule_analysis.verify_pattern_equivalence(x + y, y + x)
    assert not rule_analysis.verify_pattern_equivalence(x + y, x - y)


def test_rule_analysis_detects_equivalent_patterns() -> None:
    from d810.mba.rules.predicates import Pred0Rule1, PredOdd1

    assert rule_analysis.check_rules_equivalent(Pred0Rule1(), PredOdd1())


def test_rule_analysis_detects_inverse_rules() -> None:
    from d810.mba.rules.bnot import BnotXor_FactorRule_1
    from d810.mba.rules.cst import CstSimplificationRule16

    assert rule_analysis.check_inverse_rules(
        CstSimplificationRule16(), BnotXor_FactorRule_1()
    )


def test_rule_analysis_handles_missing_patterns() -> None:
    from d810.mba.rules._base import VerifiableRule

    class RuleWithoutPattern(VerifiableRule):
        pass

    assert not rule_analysis.check_rules_equivalent(
        RuleWithoutPattern(), RuleWithoutPattern()
    )
