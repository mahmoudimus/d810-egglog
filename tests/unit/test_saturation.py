"""Authoritative unit contracts for the optional Egglog saturation runtime."""

from __future__ import annotations

import importlib

import pytest


def test_saturation_exports_lazy_runtime_and_budget_contracts() -> None:
    saturation = importlib.import_module("d810_egglog.saturation")

    budget = saturation.EgglogExtractionBudget()

    assert budget.time_budget_ms == 3
    assert saturation._load_egglog_module() is None or saturation.egglog is not None


def test_saturation_receipt_uses_provider_neutral_egraph_contract() -> None:
    saturation = importlib.import_module("d810_egglog.saturation")
    api = importlib.import_module("d810.mba.extension_api")

    profile = api.profile_typed_term(api.TypedBvTerm(None, 8, leaf_key=("x",)))
    receipt = saturation.extraction_receipt_for_profile(
        profile, api.EgraphSkipReason.TIME_BUDGET
    )

    assert isinstance(receipt, api.EgraphExtractionReceipt)
    assert receipt.backend == "egglog"
    assert receipt.skip_reason is api.EgraphSkipReason.TIME_BUDGET


@pytest.mark.parametrize("name", ("EgglogFunctionBudget", "EgglogExtractionResult"))
def test_saturation_public_contract_names_remain_stable(name: str) -> None:
    saturation = importlib.import_module("d810_egglog.saturation")

    assert hasattr(saturation, name)
