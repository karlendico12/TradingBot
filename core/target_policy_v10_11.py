"""V10.11 target selection: preserve a feasible confirmed structural target.

The older planner always selected the nearest of fixed, structure, and the
2-ATR cap before applying the economic gate.  In quiet markets that made the
ATR cap smaller than round-trip friction and rejected a trade even when a
closer confirmed market-structure objective was economically usable.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from core.entry_policy_v10_5 import (
    StructuralTargetPlannerV10_5,
    TargetFeasibilityConfigV10_5,
)


class CostFeasibleStructuralFallbackV10_11:
    """Use structure only when the normal capped target fails economics."""

    _ECONOMIC_FAILURES = {
        "NO_POSITIVE_TARGET_ROOM",
        "ROOM_BELOW_30BPS",  # compatibility with records from older code
        "ROOM_BELOW_MINIMUM",
        "NET_REWARD_BELOW_0.75R",
        "NET_REWARD_BELOW_MINIMUM",
    }

    def __init__(
        self,
        bot: Any,
        primary: Any,
        config: TargetFeasibilityConfigV10_5,
    ) -> None:
        self.bot = bot
        self.primary = primary
        self.structure_only = StructuralTargetPlannerV10_5(config)

    def evaluate(
        self,
        side: str,
        market_price: float,
        execution: Any,
        *,
        atr14: float | None,
        opposing_levels: Iterable[float] = (),
    ):
        levels = tuple(opposing_levels)
        primary = self.primary.evaluate(
            side,
            market_price,
            execution,
            atr14=atr14,
            opposing_levels=levels,
        )
        if primary.accepted or primary.reason not in self._ECONOMIC_FAILURES or not levels:
            return primary

        # Excluding ATR_CAP here does not invent a target: the alternate
        # planner can select only the frozen 2R objective or a level that was
        # confirmed before the decision.  It must still pass both cost gates.
        alternate = self.structure_only.evaluate(
            side,
            market_price,
            execution,
            atr14=None,
            opposing_levels=levels,
        )
        if not alternate.accepted or alternate.target_source != "STRUCTURE":
            return primary

        candles = self.bot.candle_engine.get_candles()
        self.bot.policy_audit.record(
            "STRUCTURAL_TARGET_FALLBACK_ACCEPTED",
            "ATR_CAP_WAS_ECONOMICALLY_INFEASIBLE",
            event_time=int(time.time() * 1000),
            candle_time=int(candles[-1]["time"]) if candles else None,
            side=str(side).upper(),
            details={
                "primary": primary.as_dict(),
                "selected": alternate.as_dict(),
            },
        )
        return alternate
