"""Provider receipts, replay, and outer-mutation guards on native candidates."""

from __future__ import annotations

from dataclasses import replace

import pytest

ida_hexrays = pytest.importorskip("ida_hexrays")
pytest.importorskip("egglog")


@pytest.fixture(autouse=True)
def _release_native_hexrays_state():
    """Release generated microcode before the next native proof test.

    The cross-block preparation case calls ``gen_microcode`` directly.  IDA
    retains cfunc/microcode state beyond the disposable database fixture, and
    that stale state makes a later synthetic proof fail only in module order.
    Keep this acceptance module lifecycle-local instead of relying on test
    ordering or forking an already initialized IDA process.
    """

    yield
    import gc

    ida_hexrays.clear_cached_cfuncs()
    gc.collect()


from d810.mba.extension_api import compiled_rules_for_families  # noqa: E402
from d810.mba.provider_outcome import ProviderOutcomeStatus  # noqa: E402
from d810_egglog.composite_rewrite import EgglogCompositeRewrite  # noqa: E402
from d810_egglog.rules.egglog_optimizer import EgglogOptimizer  # noqa: E402
from d810_egglog.saturation import (  # noqa: E402
    EgglogExtractionBudget,
    extract_bounded_term,
)
from d810_egglog.structural_rules import structural_catalogue_for_rules  # noqa: E402
from tests.system.e2e.test_domain_lifted_semantic_simplification import (  # noqa: E402
    _native_candidate_terms,
    _native_fixed_shift_case,
    _native_semantic_instruction,
)


def _native_handler(*, time_budget_ms: int, learned_replay_enabled: bool = False):
    handler = EgglogOptimizer()
    handler.configure(
        {
            "families": ["xor"],
            "maturities": ["GLOBAL_OPTIMIZED"],
            "max_leaves": 2,
            "max_operator_nodes": 16,
            "max_degree": 1,
            "saturation_rounds": 1,
            "max_eclasses": 128,
            "max_enodes": 256,
            "max_rule_firings": 32,
            "time_budget_ms": time_budget_ms,
            "learned_replay_enabled": learned_replay_enabled,
            "require_proof": True,
        }
    )
    # The native semantic fixture intentionally reaches the extension's
    # saturation/replay path rather than the direct catalogue fast path.
    handler._direct_native_application = lambda **_kwargs: None
    handler.cross_block_constant_preparation = True
    return handler


def test_native_budget_receipt_and_interactive_extraction(monkeypatch, copy_of_idb):
    """Telemetry-only admission never loads Egglog; interactive extraction does."""

    del copy_of_idb
    telemetry = _native_handler(time_budget_ms=3)
    monkeypatch.setattr(
        telemetry,
        "_create_egglog_runtime",
        lambda: pytest.fail("telemetry-only route must not load Egglog"),
    )
    telemetry.begin_provider_outcome_capture()
    try:
        assert (
            telemetry._check_and_replace(_native_semantic_instruction(), blk=None)
            is None
        )
        telemetry_receipt = telemetry.last_extraction_receipt
        assert telemetry_receipt is not None
        assert telemetry_receipt.execution_path == "telemetry_only"
        assert telemetry_receipt.skip_reason.value == "time_budget"
        assert (
            telemetry.provider_outcomes()[-1].status
            is ProviderOutcomeStatus.OVER_BUDGET
        )
    finally:
        telemetry.end_provider_outcome_capture()

    interactive = _native_handler(time_budget_ms=1000)
    interactive.begin_provider_outcome_capture()
    try:
        assert (
            interactive._check_and_replace(_native_semantic_instruction(), blk=None)
            is not None
        )
        receipt = interactive.last_extraction_receipt
        assert receipt is not None
        assert receipt.execution_path == "fresh_saturation"
        assert receipt.selected_family == "xor"
        assert receipt.legacy_proof_verdict is True
        assert (
            interactive.provider_outcomes()[-1].status is ProviderOutcomeStatus.IMPROVED
        )
    finally:
        interactive.end_provider_outcome_capture()


def test_native_unavailable_runtime_keeps_a_runtime_receipt(copy_of_idb):
    """The bounded extractor reports an unavailable runtime, not a fake rewrite."""

    del copy_of_idb
    from d810.backends.mba.hexrays_island import lower_hexrays_island
    from d810.hexrays.ir.minsn_utils import minsn_to_ast

    instruction = _native_semantic_instruction()
    ast = minsn_to_ast(instruction)
    assert ast is not None
    lowering = lower_hexrays_island(ast, destination_size=4)
    assert lowering.raw_term is not None
    rules = compiled_rules_for_families(("xor",))
    result = extract_bounded_term(
        lowering.raw_term,
        rules,
        EgglogExtractionBudget(
            max_leaves=2,
            max_operator_nodes=16,
            max_degree=1,
            saturation_rounds=1,
            max_eclasses=128,
            max_enodes=256,
            max_rule_firings=32,
            time_budget_ms=1000,
        ),
        destination_size=4,
        profile=lowering.profile,
        catalogue=structural_catalogue_for_rules(()),
        egglog_runtime=None,
    )

    assert result.replacement_term is None
    assert result.receipt.skip_reason.value == "runtime_unavailable"
    assert result.receipt.execution_path == "fresh_saturation"


def test_cross_block_preparation_uses_a_live_native_block(copy_of_idb):
    """Cross-block preparation is exercised through the native host facade."""

    from d810.backends.mba.extension_host import native_mba_host_services
    import idaapi
    import idautils
    from tests.system.runtime.conftest import gen_microcode_at_maturity

    del copy_of_idb
    assert idaapi.init_hexrays_plugin()
    block = instruction = None
    for function_ea in idautils.Functions():
        mba = gen_microcode_at_maturity(function_ea, ida_hexrays.MMAT_GLBOPT2)
        if mba is None:
            continue
        for block_serial in range(mba.qty):
            candidate_block = mba.get_mblock(block_serial)
            if candidate_block is None or candidate_block.head is None:
                continue
            block = candidate_block
            instruction = candidate_block.head
            break
        if block is not None:
            break
    assert block is not None
    assert instruction is not None
    output = ida_hexrays.mop_t()
    output.make_reg(0, 4)
    candidate = _native_fixed_shift_case(
        ida_hexrays.m_or,
        count=7,
        root_or=True,
    )
    candidate.dst_mop = output
    host = native_mba_host_services()
    native_candidate = host.capture_ast(candidate, destination_size=4)
    prepared = host.prepare_cross_block(
        native_candidate,
        block=block,
        instruction=instruction,
        use_constants=True,
        use_def_use=True,
    )

    assert prepared is not None
    assert prepared.term is not None
    assert prepared.native_context is not None
    assert prepared.profile.width_bits == 32


class _MemoryRewriteCache:
    """Tiny cache seam retaining real native-produced rewrite records."""

    def __init__(self, rewrite=None):
        self.rewrite = rewrite

    def lookup(self, _bucket_key):
        if self.rewrite is None:
            return "miss", ()
        return "hit", (self.rewrite,)

    def store(self, rewrite):
        self.rewrite = rewrite


def test_native_replay_hit_stale_miss_and_outer_acceptance(copy_of_idb):
    """Fresh learning, replay validation, stale fallback, and final mutation state."""

    del copy_of_idb
    first = _native_handler(time_budget_ms=1000, learned_replay_enabled=True)
    cache = _MemoryRewriteCache()
    first._composite_cache = cache
    first_instruction = _native_semantic_instruction()
    from d810.hexrays.ir.minsn_utils import minsn_to_ast

    first_ast = minsn_to_ast(first_instruction)
    assert first_ast is not None
    _lowering, replacement_term = _native_candidate_terms(first_ast)

    first.begin_provider_outcome_capture()
    try:
        first_replacement = first._check_and_replace(first_instruction, blk=None)
        assert first_replacement is not None, first.last_extraction_receipt
        first_receipt = first.last_extraction_receipt
        assert first_receipt is not None
        assert first_receipt.execution_path == "fresh_saturation"
        pending = first._pending_composite_rewrite
        assert pending is not None
        first.record_mutation_accepted()
        assert first.provider_outcomes()[-1].status is ProviderOutcomeStatus.APPLIED
    finally:
        first.end_provider_outcome_capture()

    replay = _native_handler(time_budget_ms=1000, learned_replay_enabled=True)
    replay._composite_cache = cache
    replay.begin_provider_outcome_capture()
    try:
        assert replay._check_and_replace(
            _native_semantic_instruction(historical=True), blk=None
        )
        replay_receipt = replay.last_extraction_receipt
        assert replay_receipt is not None
        assert replay_receipt.execution_path == "learned_replay"
        assert replay_receipt.egraph_run_count == 0
        assert replay.provider_outcomes()[-1].status is ProviderOutcomeStatus.IMPROVED
        replay.record_mutation_accepted()
        assert replay.provider_outcomes()[-1].status is ProviderOutcomeStatus.APPLIED
    finally:
        replay.end_provider_outcome_capture()

    current = replay._current_replay_semantics()
    stale_semantics = replace(current, catalogue_digest="0" * 64)
    stale = EgglogCompositeRewrite.from_extraction(
        input_term=_lowering.raw_term or _lowering.term,
        output_term=replacement_term,
        derivation_trace=pending.derivation_trace,
        semantics=stale_semantics,
        egraph_run_count=pending.egraph_run_count,
    )
    fallback = _native_handler(time_budget_ms=1000, learned_replay_enabled=True)
    fallback._composite_cache = _MemoryRewriteCache(stale)
    fallback.begin_provider_outcome_capture()
    try:
        assert (
            fallback._check_and_replace(_native_semantic_instruction(), blk=None)
            is not None
        )
        fallback_receipt = fallback.last_extraction_receipt
        assert fallback_receipt is not None
        assert fallback_receipt.execution_path == "fresh_saturation"
        assert fallback_receipt.cache_status == "stale"
        assert fallback_receipt.replay_fallback_reason == "stale_template"
        assert fallback.provider_outcomes()[-1].status is ProviderOutcomeStatus.IMPROVED
        fallback.record_mutation_accepted()
        assert fallback.provider_outcomes()[-1].status is ProviderOutcomeStatus.APPLIED
    finally:
        fallback.end_provider_outcome_capture()
