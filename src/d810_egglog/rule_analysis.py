"""Egglog-backed analysis of relationships between MBA rules.

The analysis surface belongs to the optional extension because it constructs
Egglog expressions and runs saturation.  Core keeps only the provider-neutral
rule declarations and verification APIs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

try:
    import egglog
except ImportError:  # pragma: no cover - exercised through the probe path.
    egglog = None

if TYPE_CHECKING:
    from d810.mba.rules._base import VerifiableRule


logger = logging.getLogger(__name__)


if egglog is not None:

    class PatternExpr(egglog.Expr):
        """Expression type used for bounded rule-pattern comparisons."""

        @classmethod
        def var(cls, name: egglog.StringLike) -> "PatternExpr":
            """Create a variable expression."""

        def __add__(self, other: "PatternExpr") -> "PatternExpr": ...
        def __sub__(self, other: "PatternExpr") -> "PatternExpr": ...
        def __and__(self, other: "PatternExpr") -> "PatternExpr": ...
        def __or__(self, other: "PatternExpr") -> "PatternExpr": ...
        def __xor__(self, other: "PatternExpr") -> "PatternExpr": ...
        def __mul__(self, other: "PatternExpr") -> "PatternExpr": ...
        def __neg__(self) -> "PatternExpr": ...
        def __invert__(self) -> "PatternExpr": ...

else:

    class PatternExpr:
        """Unavailable-runtime placeholder used by the optional probe path."""

        @classmethod
        def var(cls, name: str) -> "PatternExpr":
            raise ImportError("egglog is not installed")


def _check_egglog_available() -> bool:
    """Return whether the extension's optional Egglog runtime is available."""

    return egglog is not None


def _is_symbolic_expression(value: object) -> bool:
    """Check the portable DSL shape without importing a core implementation."""

    return value is not None and callable(getattr(value, "is_leaf", None)) and all(
        hasattr(value, attribute)
        for attribute in ("operation", "left", "right", "name", "value")
    )


def _symbolic_expr_to_pattern_expr(expr, var_cache: dict | None = None):
    """Convert one DSL expression to an Egglog pattern expression."""

    if var_cache is None:
        var_cache = {}

    if expr is None:
        return None
    if not _is_symbolic_expression(expr):
        logger.debug("Cannot convert non-SymbolicExpression: %s", type(expr))
        return None
    if not _check_egglog_available():
        return None

    if expr.is_leaf():
        name = expr.name or f"leaf_{id(expr)}"
        if name not in var_cache:
            var_cache[name] = PatternExpr.var(name)
        return var_cache[name]

    operation = expr.operation
    if operation in ("add", "sub", "mul", "and", "or", "xor"):
        left = _symbolic_expr_to_pattern_expr(expr.left, var_cache)
        right = _symbolic_expr_to_pattern_expr(expr.right, var_cache)
        if left is None or right is None:
            return None
        op_map = {
            "add": lambda left_operand, right_operand: left_operand + right_operand,
            "sub": lambda left_operand, right_operand: left_operand - right_operand,
            "mul": lambda left_operand, right_operand: left_operand * right_operand,
            "and": lambda left_operand, right_operand: left_operand & right_operand,
            "or": lambda left_operand, right_operand: left_operand | right_operand,
            "xor": lambda left_operand, right_operand: left_operand ^ right_operand,
        }
        return op_map[operation](left, right)

    if operation in ("neg", "bnot"):
        operand = _symbolic_expr_to_pattern_expr(expr.left, var_cache)
        if operand is None:
            return None
        return -operand if operation == "neg" else ~operand

    logger.debug("Unsupported operation %r, treating as leaf", operation)
    name = f"op_{operation}_{id(expr)}"
    if name not in var_cache:
        var_cache[name] = PatternExpr.var(name)
    return var_cache[name]


def _collect_leaf_names(expr) -> list[str]:
    """Collect leaf names in first-occurrence order."""

    if expr is None or not _is_symbolic_expression(expr):
        return []
    if expr.is_leaf():
        return [expr.name or f"leaf_{id(expr)}"]

    names: list[str] = []
    seen: set[str] = set()
    for child in (expr.left, expr.right):
        if child is None:
            continue
        for name in _collect_leaf_names(child):
            if name not in seen:
                names.append(name)
                seen.add(name)
    return names


def _symbolic_expr_to_pattern_expr_positional(expr):
    """Convert a DSL expression using positional variable names."""

    if expr is None or not _check_egglog_available():
        return None
    positional_cache = {
        name: PatternExpr.var(f"v{index}")
        for index, name in enumerate(_collect_leaf_names(expr))
    }
    return _symbolic_expr_to_pattern_expr(expr, positional_cache)


def _get_rule_pattern(rule: "VerifiableRule"):
    """Extract a rule's declared pattern, including inherited DSL metadata."""

    for cls in type(rule).__mro__:
        if hasattr(cls, "_dsl_pattern"):
            return cls._dsl_pattern
    if hasattr(type(rule), "PATTERN"):
        return type(rule).PATTERN
    return None


def _get_rule_replacement(rule: "VerifiableRule"):
    """Extract a rule's declared replacement, including inherited metadata."""

    for cls in type(rule).__mro__:
        if hasattr(cls, "_dsl_replacement"):
            return cls._dsl_replacement
    if hasattr(type(rule), "REPLACEMENT"):
        return type(rule).REPLACEMENT
    return None


def _create_pattern_egraph():
    if not _check_egglog_available():
        raise ImportError("egglog is not installed")
    egraph = egglog.EGraph()
    a, b = egglog.vars_("a b", PatternExpr)
    egraph.register(
        egglog.rewrite(a + b).to(b + a),
        egglog.rewrite(a & b).to(b & a),
        egglog.rewrite(a | b).to(b | a),
        egglog.rewrite(a ^ b).to(b ^ a),
        egglog.rewrite(a * b).to(b * a),
        egglog.rewrite(a ^ (~b)).to(~(a ^ b)),
    )
    return egraph


def verify_pattern_equivalence(
    expr1: "PatternExpr", expr2: "PatternExpr", max_iterations: int = 10
) -> bool:
    """Check two pattern expressions for equivalence under bounded rewrites."""

    if not _check_egglog_available():
        return False
    egraph = _create_pattern_egraph()
    egraph.register(expr1, expr2)
    egraph.run(max_iterations)
    try:
        egraph.check(egglog.eq(expr1).to(expr2))
    except Exception:
        return False
    return True


def generate_equivalent_patterns(
    base_pattern: "PatternExpr",
    candidates: list["PatternExpr"],
    max_iterations: int = 10,
) -> list["PatternExpr"]:
    """Return candidate patterns equivalent to ``base_pattern``."""

    if not _check_egglog_available():
        return []
    egraph = _create_pattern_egraph()
    egraph.register(base_pattern, *candidates)
    egraph.run(max_iterations)
    equivalent = [base_pattern]
    for candidate in candidates:
        try:
            egraph.check(egglog.eq(base_pattern).to(candidate))
        except Exception:
            continue
        if candidate not in equivalent:
            equivalent.append(candidate)
    return equivalent


def check_rules_equivalent(rule1: "VerifiableRule", rule2: "VerifiableRule") -> bool:
    """Check whether two rules declare equivalent patterns."""

    if not _check_egglog_available():
        logger.warning("egglog not available for rule equivalence checking")
        return False
    pattern1 = _get_rule_pattern(rule1)
    pattern2 = _get_rule_pattern(rule2)
    if pattern1 is None or pattern2 is None:
        logger.debug("Cannot get pattern from rules: %s, %s", rule1.name, rule2.name)
        return False
    cache: dict[str, object] = {}
    expr1 = _symbolic_expr_to_pattern_expr(pattern1, cache)
    expr2 = _symbolic_expr_to_pattern_expr(pattern2, cache)
    if expr1 is None or expr2 is None:
        return False
    return verify_pattern_equivalence(expr1, expr2)


def check_inverse_rules(rule1: "VerifiableRule", rule2: "VerifiableRule") -> bool:
    """Check whether one rule's pattern matches another's replacement."""

    if not _check_egglog_available():
        logger.warning("egglog not available for inverse rule checking")
        return False
    pattern = _get_rule_pattern(rule1)
    replacement = _get_rule_replacement(rule2)
    if pattern is None or replacement is None:
        logger.debug(
            "Cannot get pattern/replacement from rules: %s, %s",
            rule1.name,
            rule2.name,
        )
        return False
    expr1 = _symbolic_expr_to_pattern_expr_positional(pattern)
    expr2 = _symbolic_expr_to_pattern_expr_positional(replacement)
    if expr1 is None or expr2 is None:
        return False
    return verify_pattern_equivalence(expr1, expr2)


def find_inverse_rule_pairs(
    rules: list["VerifiableRule"],
) -> list[tuple["VerifiableRule", "VerifiableRule"]]:
    """Find ordered rule pairs whose pattern/replacement forms a cycle."""

    if not _check_egglog_available():
        logger.warning("egglog not available for finding inverse pairs")
        return []
    inverse_pairs = []
    for index, rule1 in enumerate(rules):
        for rule2 in rules[index + 1 :]:
            if check_inverse_rules(rule1, rule2):
                inverse_pairs.append((rule1, rule2))
            if check_inverse_rules(rule2, rule1):
                inverse_pairs.append((rule2, rule1))
    return inverse_pairs


def find_equivalent_rule_patterns(
    rules: list["VerifiableRule"],
) -> list[tuple["VerifiableRule", "VerifiableRule"]]:
    """Find pairs of rules with equivalent patterns."""

    if not _check_egglog_available():
        logger.warning("egglog not available for finding equivalent patterns")
        return []
    equivalent_pairs = []
    for index, rule1 in enumerate(rules):
        for rule2 in rules[index + 1 :]:
            if check_rules_equivalent(rule1, rule2):
                equivalent_pairs.append((rule1, rule2))
    return equivalent_pairs


__all__ = [
    "PatternExpr",
    "check_inverse_rules",
    "check_rules_equivalent",
    "find_equivalent_rule_patterns",
    "find_inverse_rule_pairs",
    "generate_equivalent_patterns",
    "verify_pattern_equivalence",
]
