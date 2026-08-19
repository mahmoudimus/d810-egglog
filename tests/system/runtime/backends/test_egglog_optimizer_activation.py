from __future__ import annotations

import pytest

ida_hexrays = pytest.importorskip("ida_hexrays")

from d810.optimizers.microcode.instructions.peephole.handler import (  # noqa: E402
    PeepholeSimplificationRule,
)
from d810_egglog import MANIFEST  # noqa: E402
from d810_egglog.rules.egglog_optimizer import EgglogOptimizer  # noqa: E402


def test_destination_optimizer_imports_and_registers_in_ida_runtime() -> None:
    optimizer = EgglogOptimizer()

    assert MANIFEST["rules"] == ("d810_egglog.rules.egglog_optimizer",)
    assert MANIFEST["implements"] == {"mba-egraph": "EgglogOptimizer"}
    assert isinstance(optimizer, PeepholeSimplificationRule)
    assert optimizer.maturities == [ida_hexrays.MMAT_GLBOPT2]
