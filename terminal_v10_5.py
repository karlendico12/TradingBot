"""TradingBot V10.5: structural-room entries and neutral-first reversals.

V10.5 is a separate forward-paper experiment. It preserves V10.4's feed,
single-position ledger, costs, stops, profit guard, diagnostics, and shadow
portfolios. The actual entry/reversal policy changes are explicit and audited.
"""

from __future__ import annotations

import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox

from core.entry_policy_v10_5 import (
    ConfirmedNeutralPolicyV10_5,
    PolicyAuditStoreV10_5,
    StructuralTargetPlannerV10_5,
    TargetFeasibilityConfigV10_5,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_4 import TradingBotV10_4, TradingWindowV10_4


@dataclass(frozen=True)
class PendingActionV10_5:
    action: str
    signal: str
    candle_time: int
    decision_time_ms: int
    atr14: float | None = None
    opposing_levels: tuple[float, ...] = ()

    def status(self, event_time_ms: int, max_delay_ms: int) -> str:
        if int(event_time_ms) <= self.decision_time_ms:
            return "TOO_EARLY"
        if int(event_time_ms) - self.decision_time_ms > int(max_delay_ms):
            return "EXPIRED"
        return "ELIGIBLE"


class PolicySignalsV10_5(QObject):
    updated = pyqtSignal(str)


class TradingWindowV10_5(TradingWindowV10_4):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.5 - STRUCTURAL TARGET + CONFIRMED REVERSAL")
        self.title_label.setText(
            "TradingBot V10.5 - STRUCTURAL TARGET + CONFIRMED REVERSAL / PAPER ONLY"
        )
        self.policy_label = QLabel(
            "V10.5 Policy: WARMUP | neutral-first reversal | confirmed re-entry"
        )
        self.policy_label.setObjectName("policyStatus")
        self.policy_label.setWordWrap(True)
        self.layout.insertWidget(2, self.policy_label)
        self.setStyleSheet(
            self.styleSheet()
            + """
            QLabel#policyStatus {
                background: #172231;
                border: 1px solid #2f4968;
                border-radius: 7px;
                color: #8fc7ff;
                font-size: 14px;
                font-weight: 650;
                padding: 8px 12px;
            }
            """
        )

    def update_policy(self, text: str) -> None:
        self.policy_label.setText(f"V10.5 Policy: {text}")


class TradingBotV10_5(TradingBotV10_4):
    runtime_name = "runtime_v10_5"

    def __init__(self, window: TradingWindowV10_5) -> None:
        super().__init__(window)
        self.target_config = TargetFeasibilityConfigV10_5(
            structure_lookback_bars=40,
            level_buffer_atr=0.05,
            level_buffer_bps=1.0,
            maximum_target_atr=2.0,
            minimum_room_bps=30.0,
            minimum_net_reward_r=0.75,
        )
        self.target_planner = StructuralTargetPlannerV10_5(self.target_config)
        self.actual_policy = ConfirmedNeutralPolicyV10_5(
            confirmation_bars=2,
            cooldown_bars=1,
        )
        runtime = Path(__file__).resolve().parent / self.runtime_name
        self.policy_audit = PolicyAuditStoreV10_5(
            runtime / "policy_audit_v10_5.sqlite3"
        )
        self.policy_signals = PolicySignalsV10_5()
        self.policy_signals.updated.connect(window.update_policy)
        self._policy_audit_closed = False
        self._emit_policy("READY | waiting for a completed 3m decision")

    def print_startup_banner(self) -> None:
        print("=" * 88)
        print("TradingBot V10.5 - STRUCTURAL TARGET + CONFIRMED REVERSAL / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Entry: 2 completed 3m signals + aligned prior-60s aggressor flow")
        print("Reversal: first opposite signal exits to neutral; never flips immediately")
        print("Cooldown: one full completed 3m bar after a signal-to-neutral exit")
        print("Target: nearest of fixed 2R, confirmed structure, and 2 ATR")
        print("Entry gate: >=30bps room and >=0.75 estimated all-in net R")
        print("V10.4 profit guard, realistic costs, feed integrity, and one position retained")
        print("Daily trade-count cap: OFF; daily-loss gate: SHADOW ONLY")
        print("Use runtime_v10_5; V10.4 history remains untouched")
        print("Do not run another TradingBot version at the same time")
        print("=" * 88)

    def _emit_policy(self, text: str) -> None:
        self.policy_signals.updated.emit(str(text))

    def _handle_entry_rejection(
        self,
        pending: PendingActionV10_5,
        evaluation,
        event_time_ms: int,
        market_price: float,
    ) -> None:
        """Extension hook for later experiments; V10.5 intentionally does nothing."""
        return None

    def _recent_opposing_levels(self, side: str, decision_time: int) -> tuple[float, ...]:
        candles = self.candle_engine.get_candles()
        lookback = self.target_config.structure_lookback_bars
        cutoff = int(candles[-lookback]["time"]) if len(candles) >= lookback else 0
        points = self.structure.highs if side == "LONG" else self.structure.lows
        levels = {
            float(item["price"])
            for item in points
            if int(item["time"]) >= cutoff
            and int(item["confirmed_at"]) <= int(decision_time)
        }
        return tuple(sorted(levels))

    async def process_candle(self, candle: dict[str, Any]) -> None:
        # Parent processing continues to populate diagnostics and every shadow
        # comparator. We replace only the actual paper pending action below.
        await super().process_candle(candle)
        self.pending_entry = None
        snapshot = dict(self.latest_snapshot)
        signal = str(snapshot.get("signal", "WAIT")).upper()
        eligible = bool(snapshot.get("entry_time_eligible")) and (
            snapshot.get("safety_gate") == "PASS"
        ) and not bool(snapshot.get("data_stale"))
        current = self.position_manager.get_position()
        current_side = None if current is None else str(current["position"])
        decision = self.actual_policy.on_decision(
            signal,
            eligible=eligible,
            current_side=current_side,
            features=snapshot,
        )
        decision_time = int(candle["close_time"])
        candle_time = int(candle["time"])

        if decision.action == "EXIT_TO_NEUTRAL":
            self.pending_entry = PendingActionV10_5(
                action="EXIT_TO_NEUTRAL",
                signal=str(decision.side),
                candle_time=candle_time,
                decision_time_ms=decision_time,
            )
            text = f"OPPOSITE {decision.side} -> EXIT TO NEUTRAL (no instant flip)"
            self.signals.status.emit(text)
            self._emit_policy(text)
            return

        if decision.action == "OPEN":
            levels = self._recent_opposing_levels(str(decision.side), decision_time)
            atr_value = snapshot.get("atr14")
            atr14 = None if atr_value is None else float(atr_value)
            self.pending_entry = PendingActionV10_5(
                action="OPEN",
                signal=str(decision.side),
                candle_time=candle_time,
                decision_time_ms=decision_time,
                atr14=atr14,
                opposing_levels=levels,
            )
            text = (
                f"{decision.side} CONFIRMED; checking structural room at next fresh print"
            )
            self.signals.status.emit(text)
            self._emit_policy(text)
            return

        if signal in {"LONG", "SHORT"} or decision.reason == "COOLDOWN":
            self.policy_audit.record(
                "DECISION_SUPPRESSED",
                decision.reason,
                event_time=decision_time,
                candle_time=candle_time,
                side=signal if signal in {"LONG", "SHORT"} else None,
                details={"signal_streak": self.actual_policy.signal_streak},
            )
        self._emit_policy(
            f"{decision.reason} | signal={signal} streak={self.actual_policy.signal_streak}"
        )

    async def handle_price(
        self,
        price: float,
        event_time_ms: int,
        execution_source: str = "UNKNOWN",
    ) -> None:
        # This is the V10 execution path with the single intentional policy
        # change: EXIT_TO_NEUTRAL never opens the opposite side on this print.
        self.path_tracker.observe(price, event_time_ms)
        try:
            price = float(price)
            event_time_ms = int(event_time_ms)
            event_age_ms = int(time.time() * 1000) - event_time_ms
            if not -1_000 <= event_age_ms <= self.config.max_entry_delay_ms:
                print(
                    "[INTEGRITY] Suppressed stale aggregate trade from forward "
                    f"execution source={execution_source} age_ms={event_age_ms}"
                )
                return
            self.last_price = price
            self.last_price_event_time = event_time_ms
            self._publish_visual_price(price, event_time_ms, execution_source)
            monotonic_now = time.monotonic()
            refresh_gui = monotonic_now - self._last_pnl_gui_emit >= 0.10
            if refresh_gui:
                self._last_pnl_gui_emit = monotonic_now

            trade = self.position_manager.check_exit(
                price, event_time_ms, execution_source
            )
            if trade is not None:
                self._record_closed_trade(trade)
            else:
                position = self.position_manager.update_unrealized_pnl(price)
                if position is not None and refresh_gui:
                    self.signals.current_pnl.emit(float(position["current_pnl"]))

            pending = self.pending_entry
            if pending is None:
                return
            status = pending.status(event_time_ms, self.config.max_entry_delay_ms)
            if status == "TOO_EARLY":
                return
            self.pending_entry = None
            if status == "EXPIRED":
                self.signals.status.emit("V10.5 action cancelled: no timely next print")
                self._emit_policy("ACTION EXPIRED; no execution")
                return

            current = self.position_manager.get_position()
            if pending.action == "EXIT_TO_NEUTRAL":
                if current is not None and str(current["position"]) != pending.signal:
                    closed = self.position_manager.close_position(
                        price,
                        "SIGNAL TO NEUTRAL",
                        event_time_ms,
                        execution_source,
                    )
                    self._record_closed_trade(closed)
                    self.actual_policy.mark_signal_exit()
                    self.policy_audit.record(
                        "SIGNAL_TO_NEUTRAL",
                        "FIRST_OPPOSITE",
                        event_time=event_time_ms,
                        candle_time=pending.candle_time,
                        side=pending.signal,
                        details={"market_price": price},
                    )
                    self._emit_policy(
                        "FLAT after opposite signal; one completed-bar cooldown active"
                    )
                return

            if pending.action != "OPEN" or current is not None:
                return
            evaluation = self.target_planner.evaluate(
                pending.signal,
                price,
                self.config,
                atr14=pending.atr14,
                opposing_levels=pending.opposing_levels,
            )
            if not evaluation.accepted:
                self.policy_audit.record(
                    "ENTRY_REJECTED",
                    evaluation.reason,
                    event_time=event_time_ms,
                    candle_time=pending.candle_time,
                    side=pending.signal,
                    details=evaluation.as_dict(),
                )
                text = (
                    f"{pending.signal} REJECTED: {evaluation.reason} | "
                    f"room={evaluation.room_bps:.1f}bps "
                    f"net={evaluation.estimated_net_reward_r:+.2f}R"
                )
                print(f"[V10.5 TARGET GATE] {text}", flush=True)
                self.signals.status.emit(text)
                self._emit_policy(text)
                self._handle_entry_rejection(
                    pending,
                    evaluation,
                    event_time_ms,
                    price,
                )
                return

            self._open_at_observed_price(
                pending, price, event_time_ms, execution_source
            )
            position = self.position_manager.get_position()
            if position is None:
                return
            position["version"] = "10.5"
            position["take_profit"] = evaluation.selected_target_market
            metadata = dict(position.get("metadata", {}))
            metadata["v10_5_target_evaluation"] = evaluation.as_dict()
            metadata["v10_5_entry_policy"] = {
                "confirmation_bars": self.actual_policy.confirmation_bars,
                "cooldown_bars": self.actual_policy.cooldown_bars,
                "neutral_first": True,
            }
            position["metadata"] = metadata
            self.store.save_position(position)
            self.signals.position.emit(position)
            self.policy_audit.record(
                "ENTRY_ACCEPTED",
                evaluation.target_source,
                event_time=event_time_ms,
                candle_time=pending.candle_time,
                side=pending.signal,
                details=evaluation.as_dict(),
            )
            text = (
                f"{pending.signal} OPEN | target={evaluation.target_source} "
                f"room={evaluation.room_bps:.1f}bps "
                f"net={evaluation.estimated_net_reward_r:+.2f}R"
            )
            self._emit_policy(text)
        except Exception:
            self.running = False
            self.signals.status.emit("FATAL V10.5 execution error; inspect terminal")
            traceback.print_exc()

    async def stop(self) -> None:
        try:
            await super().stop()
        finally:
            if not self._policy_audit_closed:
                self.policy_audit.close()
                self._policy_audit_closed = True


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_5.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.5 already running",
            "Another V10.5 instance already owns this project. Close it first.",
        )
        return 2

    window = TradingWindowV10_5()
    window.showMaximized()
    bot = TradingBotV10_5(window)
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
