"""Native activation and direct-catalogue acceptance for the Egglog backend."""

from __future__ import annotations

import pytest

ida_hexrays = pytest.importorskip("ida_hexrays")
pytest.importorskip("egglog")

from d810.backends import registry  # noqa: E402
from d810.core.plugins import BackendStatus  # noqa: E402
from d810.mba.extension_api import compiled_rules_for_families  # noqa: E402
from d810_egglog.rules.egglog_optimizer import EgglogOptimizer  # noqa: E402
from tests.system.e2e.test_domain_lifted_semantic_simplification import (  # noqa: E402
    _native_semantic_instruction,
)


def test_manifest_probe_activates_one_native_rule() -> None:
    """The installed entry point resolves and registers its declared rule."""

    from d810.optimizers.microcode.instructions.handler import (  # noqa: PLC0415
        InstructionOptimizationRule,
    )

    backend_registry = registry()
    candidate = backend_registry.require_unique_implementation(
        "mba-egraph",
        install_hint="d810-egglog",
    )
    assert candidate.backend_name == "egglog"
    assert candidate.rule_name == "EgglogOptimizer"
    assert candidate.rule_modules == ("d810_egglog.rules.egglog_optimizer",)

    backend_registry.activate_implementation(candidate)

    assert backend_registry.probe("egglog").status is BackendStatus.AVAILABLE
    assert InstructionOptimizationRule.find("EgglogOptimizer") is not None


def test_native_direct_catalogue_reduction_selects_strict_rule(copy_of_idb) -> None:
    """A native minsn reaches the certified direct catalogue before Egglog."""

    from d810.hexrays.ir.minsn_utils import minsn_to_ast
    from d810.mba.extension_api import term_cost
    from d810_egglog.rule_lowering import canonical_pattern_catalogue_for_rules

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
    del copy_of_idb
    instruction = _native_semantic_instruction()
    ast = minsn_to_ast(instruction)
    assert ast is not None
    native_candidate = optimizer._host.capture_ast(ast, destination_size=4)
    rule = next(
        rule
        for rule in compiled_rules_for_families(("xor",))
        if rule.source_name == "Xor_HackersDelightRule_3"
    )
    optimizer._catalogue = type("Selected", (), {"compiled_rules": (rule,)})()
    catalogue = canonical_pattern_catalogue_for_rules((rule,))
    match_report = catalogue.canonical_applications(
        native_candidate.term,
        comparison_budget=64,
    )
    applications = (
        match_report.applications
        if hasattr(match_report, "applications")
        else tuple(match_report)
    )
    selected = optimizer._direct_native_application(
        candidate_term=native_candidate.term,
        structural_route=False,
        structural_matches=(),
        match_result=None,
        canonical_match_result=None,
        applications=applications,
    )

    assert selected is not None
    replacement_term, provenance = selected
    assert provenance[0] == "xor"
    assert term_cost(replacement_term) < term_cost(native_candidate.term)
