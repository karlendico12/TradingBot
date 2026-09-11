"""TradingBot V10.8: significant structure and controlled gate relaxation."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Iterable

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.entry_policy_v10_5 import (
    StructuralTargetPlannerV10_5,
    TargetFeasibilityConfigV10_5,
)
from core.significant_structure_v10_8 import (
    SignificantStructureConfigV10_8,
    SignificantStructureSelectorV10_8,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_7 import TradingBotV10_7, TradingWindowV10_7


class TradingWindowV10_8(TradingWindowV10_7):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.8 - SIGNIFICANT STRUCTURE")
        self.title_label.setText(
            "TradingBot V10.8 - SIGNIFICANT STRUCTURE / PAPER ONLY"
        )
        self.policy_label.setText(
            "V10.8 Policy: WARMUP | significant levels + controlled cost gate"
        )

    def update_policy(self, text: str) -> None:
        self.policy_label.setText(f"V10.8 Policy: {text}")


class ComparingTargetPlannerV10_8:
    """Return V10.8's decision while auditing the legacy V10.7 target gate."""

    def __init__(
        self,
        bot: "TradingBotV10_8",
        relaxed: StructuralTargetPlannerV10_5,
        strict: StructuralTargetPlannerV10_5,
    ) -> None:
        self.bot = bot
        self.relaxed = relaxed
        self.strict = strict

    def evaluate(
        self,
        side: str,
        market_price: float,
        execution,
        *,
        atr14: float | None,
        opposing_levels: Iterable[float] = (),
    ):
        relaxed_result = self.relaxed.evaluate(
            side,
            market_price,
            execution,
            atr14=atr14,
            opposing_levels=opposing_levels,
        )
        candles = self.bot.candle_engine.get_candles()
        decision_time = (
            int(candles[-1].get("close_time", candles[-1]["time"]))
            if candles
            else int(time.time() * 1000)
        )
        cutoff = int(candles[-40]["time"]) if len(candles) >= 40 else 0
        raw_points = (
            self.bot.structure.highs
            if str(side).upper() == "LONG"
            else self.bot.structure.lows
        )
        raw_levels = tuple(
            sorted(
                {
                    float(item["price"])
                    for item in raw_points
                    if int(item["time"]) >= cutoff
                    and int(item["confirmed_at"]) <= decision_time
                }
            )
        )
        strict_result = self.strict.evaluate(
            side,
            market_price,
            execution,
            atr14=atr14,
            opposing_levels=raw_levels,
        )
        event_type = (
            "STRICT_SHADOW_PASS"
            if strict_result.accepted
            else "STRICT_SHADOW_REJECTED"
        )
        self.bot.policy_audit.record(
            event_type,
            strict_result.reason,
            event_time=int(time.time() * 1000),
            candle_time=int(candles[-1]["time"]) if candles else None,
            side=str(side),
            details={
                "strict_v10_7": strict_result.as_dict(),
                "actual_v10_8": relaxed_result.as_dict(),
                "raw_level_count": len(raw_levels),
                "significant_level_count": len(tuple(opposing_levels)),
            },
        )
        return relaxed_result


class TradingBotV10_8(TradingBotV10_7):
    runtime_name = "runtime_v10_8"

    def __init__(self, window: TradingWindowV10_8) -> None:
        super().__init__(window)
        self.significant_selector = SignificantStructureSelectorV10_8(
            SignificantStructureConfigV10_8(
                lookback_bars=60,
                cluster_atr=0.12,
                minimum_cluster_bps=2.0,
                minimum_prominence_atr=0.50,
                repeated_touches=2,
                neighbor_bars=3,
            )
        )
        self.target_config = TargetFeasibilityConfigV10_5(
            structure_lookback_bars=60,
            level_buffer_atr=0.05,
            level_buffer_bps=1.0,
            maximum_target_atr=2.0,
            minimum_room_bps=18.0,
            minimum_net_reward_r=0.35,
        )
        relaxed = StructuralTargetPlannerV10_5(self.target_config)
        strict = StructuralTargetPlannerV10_5(
            TargetFeasibilityConfigV10_5(
                structure_lookback_bars=40,
                level_buffer_atr=0.05,
                level_buffer_bps=1.0,
                maximum_target_atr=2.0,
                minimum_room_bps=30.0,
                minimum_net_reward_r=0.75,
            )
        )
        self.target_planner = ComparingTargetPlannerV10_8(self, relaxed, strict)

    def print_startup_banner(self) -> None:
        print("=" * 94)
        print("TradingBot V10.8 - SIGNIFICANT STRUCTURE / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Structure: cluster nearby pivots; keep repeated or >=0.50 ATR prominence")
        print("Actual target gate: >=18bps room and >=0.35 estimated all-in net R")
        print("V10.7 legacy 30bps / 0.75R gate recorded in strict shadow")
        print("Direction, live-flow watch, breakout watch, and anti-chase retained")
        print("Neutral-first reversal, V10.4 profit guard, and realistic costs retained")
        print("Daily trade-count cap: OFF; one actual paper position")
        print("Use runtime_v10_8; earlier histories remain untouched")
        print("Do not run another TradingBot version at the same time")
        print("=" * 94)

    def _recent_opposing_levels(self, side: str, decision_time: int) -> tuple[float, ...]:
        candles = self.candle_engine.get_candles()
        snapshot = dict(self.latest_snapshot)
        atr_value = snapshot.get("atr14")
        points = self.structure.highs if str(side).upper() == "LONG" else self.structure.lows
        return self.significant_selector.select(
            side=str(side),
            candles=candles,
            points=points,
            decision_time=int(decision_time),
            atr14=None if atr_value is None else float(atr_value),
        )


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_8.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.8 already running",
            "Another V10.8 instance already owns this project. Close it first.",
        )
        return 2

    window = TradingWindowV10_8()
    window.showMaximized()
    bot = TradingBotV10_8(window)
    window.bot = bot
    runner = AsyncBotRunner(bot)
    window.bot_runner = runner
    runner.start()
    try:
        return app.exec()
    finally:
        runner.stop()
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
