"""TradingBot V10.6: V10.5 plus a causal intrabar breakout watch."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.breakout_watch_v10_6 import (
    BreakoutWatchConfigV10_6,
    BreakoutWatchV10_6,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_5 import (
    PendingActionV10_5,
    TradingBotV10_5,
    TradingWindowV10_5,
)


class TradingWindowV10_6(TradingWindowV10_5):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.6 - CAUSAL INTRABAR BREAKOUT")
        self.title_label.setText(
            "TradingBot V10.6 - CAUSAL INTRABAR BREAKOUT / PAPER ONLY"
        )
        self.policy_label.setText(
            "V10.6 Policy: WARMUP | completed-bar setup + raw-trade breakout watch"
        )


class TradingBotV10_6(TradingBotV10_5):
    runtime_name = "runtime_v10_6"

    def __init__(self, window: TradingWindowV10_6) -> None:
        super().__init__(window)
        self.breakout_watch = BreakoutWatchV10_6(
            BreakoutWatchConfigV10_6(
                lifetime_ms=180_000,
                break_buffer_bps=2.0,
                reclaim_buffer_bps=1.0,
                confirmation_ms=1_000,
                minimum_trade_count_60s=20,
                minimum_abs_flow_imbalance=0.05,
            )
        )

    def print_startup_banner(self) -> None:
        print("=" * 92)
        print("TradingBot V10.6 - CAUSAL INTRABAR BREAKOUT / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Normal policy: V10.5 confirmed entry + neutral-first reversal")
        print("Breakout watch: armed only after a STRUCTURE-room entry rejection")
        print("Watch life: 180s; break: 2bps; hold: 1s; reclaim cancellation: 1bp")
        print("Live flow: >=20 prior-60s trades and |imbalance| >=0.05 aligned")
        print("Breakout entry must pass a fresh >=30bps / >=0.75 net-R target check")
        print("No arbitrary forming-candle LONG/SHORT decisions; ML remains OFF")
        print("Daily trade-count cap: OFF; one actual paper position")
        print("Use runtime_v10_6; all earlier runtime histories remain untouched")
        print("Do not run another TradingBot version at the same time")
        print("=" * 92)

    def _cancel_breakout_watch(self, reason: str, event_time: int) -> None:
        prior = self.breakout_watch.cancel()
        if prior is None:
            return
        self.policy_audit.record(
            "BREAKOUT_WATCH_CANCELLED",
            reason,
            event_time=event_time,
            candle_time=prior.candle_time,
            side=prior.side,
            details=prior.as_dict(),
        )

    async def process_candle(self, candle: dict[str, Any]) -> None:
        # A watch is valid only inside the decision interval that armed it.
        state = self.breakout_watch.state
        if state is not None and int(candle["close_time"]) > state.decision_time:
            self._cancel_breakout_watch(
                "NEW_COMPLETED_DECISION",
                int(candle["close_time"]),
            )
        await super().process_candle(candle)

    def _handle_entry_rejection(
        self,
        pending: PendingActionV10_5,
        evaluation,
        event_time_ms: int,
        market_price: float,
    ) -> None:
        # ATR-only and fixed-target rejections do not define a price level that
        # can causally authorize a later breakout.
        if (
            evaluation.reason
            not in {
                "NO_POSITIVE_TARGET_ROOM",
                "ROOM_BELOW_30BPS",
                "ROOM_BELOW_MINIMUM",
            }
            or evaluation.target_source != "STRUCTURE"
            or evaluation.structural_level is None
        ):
            return
        state = self.breakout_watch.arm(
            side=pending.signal,
            level=float(evaluation.structural_level),
            candle_time=pending.candle_time,
            decision_time=pending.decision_time_ms,
            armed_time=event_time_ms,
            atr14=pending.atr14,
            opposing_levels=pending.opposing_levels,
        )
        self.policy_audit.record(
            "BREAKOUT_WATCH_ARMED",
            evaluation.reason,
            event_time=event_time_ms,
            candle_time=pending.candle_time,
            side=pending.signal,
            details={
                "watch": state.as_dict(),
                "rejected_evaluation": evaluation.as_dict(),
                "market_price": float(market_price),
            },
        )
        text = (
            f"{pending.signal} WATCH ARMED at {state.level:.2f} | "
            "waiting for 2bp trade-through + 1s hold + aligned flow"
        )
        print(f"[V10.6 BREAKOUT] {text}", flush=True)
        self.signals.status.emit(text)
        self._emit_policy(text)

    def _open_breakout_position(
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
        position["version"] = "10.6"
        position["take_profit"] = evaluation.selected_target_market
        metadata = dict(position.get("metadata", {}))
        metadata["v10_6_breakout_entry"] = {
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
        state = self.breakout_watch.state
        if state is None:
            return
        if self.position_manager.has_position():
            self._cancel_breakout_watch("POSITION_ALREADY_OPEN", int(trade["event_time"]))
            return
        if not bool(trade.get("entry_eligible", False)):
            return

        event_time = int(trade["event_time"])
        price = float(trade["price"])
        flow = self.order_flow.snapshot(event_time)
        observation = self.breakout_watch.observe(
            price=price,
            event_time=event_time,
            trade_count_60s=int(flow.get("trade_count_60s") or 0),
            flow_imbalance_60s=float(flow.get("flow_imbalance_60s") or 0.0),
        )
        if observation.cancel:
            self._cancel_breakout_watch(observation.reason, event_time)
            self._emit_policy(f"BREAKOUT WATCH CANCELLED: {observation.reason}")
            return
        if not observation.trigger:
            if observation.status == "CONFIRMING":
                self._emit_policy(
                    f"{state.side} BREAKOUT CONFIRMING | level={state.level:.2f}"
                )
            return

        # Remove the consumed level. The planner also direction-filters it,
        # but explicit removal makes the causal intent auditable.
        remaining_levels = tuple(
            level
            for level in state.opposing_levels
            if abs(float(level) - state.level) > 1e-9
        )
        evaluation = self.target_planner.evaluate(
            state.side,
            price,
            self.config,
            atr14=state.atr14,
            opposing_levels=remaining_levels,
        )
        consumed = self.breakout_watch.cancel()
        if consumed is None:
            return
        if not evaluation.accepted:
            self.policy_audit.record(
                "BREAKOUT_ENTRY_REJECTED",
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
            text = (
                f"{consumed.side} BREAK CONFIRMED but target rejected: "
                f"{evaluation.reason} room={evaluation.room_bps:.1f}bps"
            )
            print(f"[V10.6 BREAKOUT] {text}", flush=True)
            self._emit_policy(text)
            return

        self._open_breakout_position(
            consumed,
            evaluation,
            price,
            event_time,
            str(trade.get("source", "UNKNOWN")),
            flow,
        )
        self.policy_audit.record(
            "BREAKOUT_ENTRY_ACCEPTED",
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
            f"{consumed.side} BREAKOUT OPEN | target={evaluation.target_source} "
            f"room={evaluation.room_bps:.1f}bps net={evaluation.estimated_net_reward_r:+.2f}R"
        )
        print(f"[V10.6 BREAKOUT] {text}", flush=True)
        self._emit_policy(text)

    async def stop(self) -> None:
        state = self.breakout_watch.state
        if state is not None:
            self._cancel_breakout_watch("SHUTDOWN", state.expiry_time)
        await super().stop()


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_6.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.6 already running",
            "Another V10.6 instance already owns this project. Close it first.",
        )
        return 2

    window = TradingWindowV10_6()
    window.showMaximized()
    bot = TradingBotV10_6(window)
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
