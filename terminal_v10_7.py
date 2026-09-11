"""TradingBot V10.7: V10.6 plus intrabar flow-alignment entry watches."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.flow_alignment_watch_v10_7 import (
    FlowAlignmentWatchConfigV10_7,
    FlowAlignmentWatchV10_7,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_5 import PendingActionV10_5
from terminal_v10_6 import TradingBotV10_6, TradingWindowV10_6


class TradingWindowV10_7(TradingWindowV10_6):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.7 - LIVE FLOW ALIGNMENT")
        self.title_label.setText(
            "TradingBot V10.7 - LIVE FLOW ALIGNMENT / PAPER ONLY"
        )
        self.policy_label.setText(
            "V10.7 Policy: WARMUP | confirmed direction + live flow watch"
        )


class TradingBotV10_7(TradingBotV10_6):
    runtime_name = "runtime_v10_7"

    def __init__(self, window: TradingWindowV10_7) -> None:
        super().__init__(window)
        self.flow_watch = FlowAlignmentWatchV10_7(
            FlowAlignmentWatchConfigV10_7(
                lifetime_ms=180_000,
                confirmation_ms=1_000,
                minimum_trade_count_60s=20,
                minimum_abs_flow_imbalance=0.05,
                maximum_chase_bps=20.0,
            )
        )

    def _uses_v10_7_flow_watch(self) -> bool:
        return True

    def print_startup_banner(self) -> None:
        print("=" * 92)
        print("TradingBot V10.7 - LIVE FLOW ALIGNMENT / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Direction: at least 2 consecutive completed 3m V9 signals")
        print("If flow is initially unaligned: watch raw trades for up to 180s")
        print("Live entry: aligned |imbalance|>=0.05 held 1s with >=20 trades/60s")
        print("Anti-chase: cancel after a favorable move greater than 20bps")
        print("Every entry still requires >=30bps target room and >=0.75 net R")
        print("V10.6 structural-break watch and V10.5 neutral-first exits retained")
        print("No arbitrary green/red candle decisions; ML remains OFF")
        print("Daily trade-count cap: OFF; one actual paper position")
        print("Use runtime_v10_7; earlier histories remain untouched")
        print("Do not run another TradingBot version at the same time")
        print("=" * 92)

    def _cancel_flow_watch(self, reason: str, event_time: int) -> None:
        prior = self.flow_watch.cancel()
        if prior is None:
            return
        self.policy_audit.record(
            "FLOW_WATCH_CANCELLED",
            reason,
            event_time=event_time,
            candle_time=prior.candle_time,
            side=prior.side,
            details=prior.as_dict(),
        )

    async def process_candle(self, candle: dict[str, Any]) -> None:
        if not self._uses_v10_7_flow_watch():
            await super().process_candle(candle)
            return

        prior = self.flow_watch.state
        if prior is not None and int(candle["close_time"]) > prior.decision_time:
            self._cancel_flow_watch("NEW_COMPLETED_DECISION", int(candle["close_time"]))
        await super().process_candle(candle)

        snapshot = dict(self.latest_snapshot)
        signal = str(snapshot.get("signal", "WAIT")).upper()
        eligible = bool(snapshot.get("entry_time_eligible")) and (
            snapshot.get("safety_gate") == "PASS"
        ) and not bool(snapshot.get("data_stale"))
        if (
            not eligible
            or signal not in {"LONG", "SHORT"}
            or self.position_manager.has_position()
            or self.pending_entry is not None
            or self.breakout_watch.state is not None
            or self.actual_policy.signal_streak < self.actual_policy.confirmation_bars
            or self.actual_policy.flow_aligned(signal, snapshot)
        ):
            return

        decision_time = int(candle["close_time"])
        atr_value = snapshot.get("atr14")
        state = self.flow_watch.arm(
            side=signal,
            candle_time=int(candle["time"]),
            decision_time=decision_time,
            decision_price=float(candle["close"]),
            atr14=None if atr_value is None else float(atr_value),
            opposing_levels=self._recent_opposing_levels(signal, decision_time),
        )
        self.policy_audit.record(
            "FLOW_WATCH_ARMED",
            "COMPLETED_DIRECTION_FLOW_PENDING",
            event_time=decision_time,
            candle_time=state.candle_time,
            side=state.side,
            details=state.as_dict(),
        )
        text = (
            f"{signal} DIRECTION CONFIRMED | watching live flow for up to 180s"
        )
        print(f"[V10.7 FLOW] {text}", flush=True)
        self.signals.status.emit(text)
        self._emit_policy(text)

    def _open_flow_position(
        self,
        state,
        evaluation,
        price: float,
        event_time: int,
        source: str,
        flow: dict[str, Any],
    ) -> None:
        pending = PendingActionV10_5(
            action="OPEN",
            signal=state.side,
            candle_time=state.candle_time,
            decision_time_ms=state.decision_time,
            atr14=state.atr14,
            opposing_levels=state.opposing_levels,
        )
        self._open_at_observed_price(pending, price, event_time, source)
        position = self.position_manager.get_position()
        if position is None:
            return
        position["version"] = "10.7"
        position["take_profit"] = evaluation.selected_target_market
        metadata = dict(position.get("metadata", {}))
        metadata["v10_7_flow_entry"] = {
            "watch": state.as_dict(),
            "target_evaluation": evaluation.as_dict(),
            "trigger_flow": dict(flow),
        }
        metadata["v10_5_target_evaluation"] = evaluation.as_dict()
        metadata["v10_5_entry_policy"] = {
            "confirmation_bars": self.actual_policy.confirmation_bars,
            "cooldown_bars": self.actual_policy.cooldown_bars,
            "neutral_first": True,
        }
        position["metadata"] = metadata
        self.store.save_position(position)
        self.signals.position.emit(position)

    async def handle_trade_event(self, trade: dict[str, Any]) -> None:
        await super().handle_trade_event(trade)
        state = self.flow_watch.state
        if state is None:
            return
        event_time = int(trade["event_time"])
        if self.position_manager.has_position():
            self._cancel_flow_watch("POSITION_ALREADY_OPEN", event_time)
            return
        if not bool(trade.get("entry_eligible", False)):
            return

        price = float(trade["price"])
        flow = self.order_flow.snapshot(event_time)
        observation = self.flow_watch.observe(
            price=price,
            event_time=event_time,
            trade_count_60s=int(flow.get("trade_count_60s") or 0),
            flow_imbalance_60s=float(flow.get("flow_imbalance_60s") or 0.0),
        )
        if observation.cancel:
            self._cancel_flow_watch(observation.reason, event_time)
            self._emit_policy(f"FLOW WATCH CANCELLED: {observation.reason}")
            return
        if not observation.trigger:
            if observation.status == "CONFIRMING":
                self._emit_policy(
                    f"{state.side} LIVE FLOW CONFIRMING | "
                    f"imbalance={float(flow.get('flow_imbalance_60s') or 0.0):+.3f}"
                )
            return

        evaluation = self.target_planner.evaluate(
            state.side,
            price,
            self.config,
            atr14=state.atr14,
            opposing_levels=state.opposing_levels,
        )
        consumed = self.flow_watch.cancel()
        if consumed is None:
            return
        pending = PendingActionV10_5(
            action="OPEN",
            signal=consumed.side,
            candle_time=consumed.candle_time,
            decision_time_ms=consumed.decision_time,
            atr14=consumed.atr14,
            opposing_levels=consumed.opposing_levels,
        )
        if not evaluation.accepted:
            self.policy_audit.record(
                "FLOW_ENTRY_REJECTED",
                evaluation.reason,
                event_time=event_time,
                candle_time=consumed.candle_time,
                side=consumed.side,
                details={
                    "watch": consumed.as_dict(),
                    "target_evaluation": evaluation.as_dict(),
                    "trigger_flow": flow,
                },
            )
            # A structure-room rejection can transition into V10.6's breakout
            # watch instead of being forgotten.
            self._handle_entry_rejection(
                pending,
                evaluation,
                event_time,
                price,
            )
            text = (
                f"{consumed.side} FLOW CONFIRMED but target rejected: "
                f"{evaluation.reason} room={evaluation.room_bps:.1f}bps"
            )
            print(f"[V10.7 FLOW] {text}", flush=True)
            if self.breakout_watch.state is None:
                self._emit_policy(text)
            return

        self._open_flow_position(
            consumed,
            evaluation,
            price,
            event_time,
            str(trade.get("source", "UNKNOWN")),
            flow,
        )
        self.policy_audit.record(
            "FLOW_ENTRY_ACCEPTED",
            evaluation.target_source,
            event_time=event_time,
            candle_time=consumed.candle_time,
            side=consumed.side,
            details={
                "watch": consumed.as_dict(),
                "target_evaluation": evaluation.as_dict(),
                "trigger_flow": flow,
            },
        )
        text = (
            f"{consumed.side} LIVE-FLOW OPEN | target={evaluation.target_source} "
            f"room={evaluation.room_bps:.1f}bps net={evaluation.estimated_net_reward_r:+.2f}R"
        )
        print(f"[V10.7 FLOW] {text}", flush=True)
        self._emit_policy(text)

    async def stop(self) -> None:
        state = self.flow_watch.state
        if state is not None:
            self._cancel_flow_watch("SHUTDOWN", int(time.time() * 1000))
        await super().stop()


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_7.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.7 already running",
            "Another V10.7 instance already owns this project. Close it first.",
        )
        return 2

    window = TradingWindowV10_7()
    window.showMaximized()
    bot = TradingBotV10_7(window)
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
