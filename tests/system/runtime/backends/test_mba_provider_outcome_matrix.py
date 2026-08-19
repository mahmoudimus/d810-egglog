"""Egglog provider outcome matrix cases owned by the optional extension."""

from __future__ import annotations

from d810.mba.egraph_contracts import EgraphExtractionReceipt, EgraphSkipReason
from d810.mba.provider_outcome import ProviderOutcomeStatus
from d810_egglog.rules.egglog_optimizer import EgglogOptimizer


def test_egglog_attempt_matrix_retains_one_final_row_per_skip_or_proof_result() -> None:
    handler = EgglogOptimizer()
    handler.begin_provider_outcome_capture()
    receipts = (
        EgraphExtractionReceipt(skip_reason=EgraphSkipReason.RUNTIME_UNAVAILABLE),
        EgraphExtractionReceipt(skip_reason=EgraphSkipReason.TIME_BUDGET),
        EgraphExtractionReceipt(skip_reason=EgraphSkipReason.PROOF_FAILED),
        EgraphExtractionReceipt(input_cost=(4, 7), extracted_cost=(4, 7)),
    )

    for receipt in receipts:
        handler._begin_provider_attempt()
        handler._record_extraction_receipt(receipt)

    assert [outcome.status for outcome in handler.provider_outcomes()] == [
        ProviderOutcomeStatus.UNAVAILABLE,
        ProviderOutcomeStatus.OVER_BUDGET,
        ProviderOutcomeStatus.PROOF_FAILED,
        ProviderOutcomeStatus.UNCHANGED,
    ]

    handler._begin_provider_attempt()
    handler._record_extraction_receipt(
        EgraphExtractionReceipt(input_cost=(4, 7), extracted_cost=(2, 3))
    )
    handler._record_extraction_receipt(
        EgraphExtractionReceipt(skip_reason=EgraphSkipReason.PROOF_FAILED)
    )
    assert len(handler.provider_outcomes()) == 5
    assert handler.provider_outcomes()[-1].status is ProviderOutcomeStatus.PROOF_FAILED


def test_egglog_candidate_is_only_applied_after_outer_mutation_acceptance() -> None:
    handler = EgglogOptimizer()
    handler.begin_provider_outcome_capture()
    handler._begin_provider_attempt()
    handler._record_extraction_receipt(
        EgraphExtractionReceipt(input_cost=(4, 7), extracted_cost=(2, 3))
    )

    assert handler.provider_outcomes()[-1].status is ProviderOutcomeStatus.IMPROVED

    handler.record_mutation_accepted()

    assert handler.provider_outcomes()[-1].status is ProviderOutcomeStatus.APPLIED
