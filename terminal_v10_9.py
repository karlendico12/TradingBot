"""TradingBot V10.9: fast live entry, guarded intrabar reversal, and evidence exit."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.fast_adaptation_v10_9 import (
    FastEvidenceExitConfigV10_9,
    FastEvidenceExitV10_9,
    FastInitialEntryConfigV10_9,
    FastInitialEntryWatchV10_9,
    FastIntrabarReversalConfigV10_9,
    FastIntrabarReversalWatchV10_9,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_5 import PendingActionV10_5
from terminal_v10_8 import TradingBotV10_8, TradingWindowV10_8


class TradingWindowV10_9(TradingWindowV10_8):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.9 - FAST ADAPTATION")
        self.title_label.setText(
            "TradingBot V10.9 - FAST ADAPTATION / PAPER ONLY"
        )
        self.policy_label.setText(
            "V10.9 Policy: WARMUP | first-signal live entry + evidence exit"
        )

    def update_policy(self, text: str) -> None:
        self.policy_label.setText(f"V10.9 Policy: {text}")

    def update_signal(self, signal: str) -> None:
        super().update_signal(signal)
        # This value changes only when a 3-minute candle completes. The live
        # policy strip below it reports intrabar watches and overrides.
        self.signal_label.setText(f"Closed 3m Signal: {signal}")


class TradingBotV10_9(TradingBotV10_8):
    runtime_name = "runtime_v10_9"

    def __init__(self, window: TradingWindowV10_9) -> None:
        super().__init__(window)
        self.fast_entry_watch = FastInitialEntryWatchV10_9(
            FastInitialEntryConfigV10_9(
                lifetime_ms=180_000,
                break_buffer_bps=1.0,
                confirmation_ms=1_000,
                minimum_trade_count_60s=20,
                minimum_abs_flow_imbalance=0.05,
                maximum_chase_bps=12.0,
            )
        )
        self.reversal_watch = FastIntrabarReversalWatchV10_9(
            FastIntrabarReversalConfigV10_9(
                lifetime_ms=180_000,
                ema_buffer_bps=2.0,
                extreme_break_bps=1.0,
                confirmation_ms=2_000,
                minimum_trade_count_60s=20,
                minimum_abs_flow_imbalance=0.15,
                maximum_chase_bps=15.0,
            )
        )
        self.evidence_exit = FastEvidenceExitV10_9(
            FastEvidenceExitConfigV10_9(
                confirmation_ms=2_000,
                minimum_trade_count_60s=20,
                minimum_abs_adverse_imbalance=0.10,
                maximum_losing_net_r=-0.20,
                maximum_losing_gross_r=-0.05,
                giveback_arm_net_r=0.20,
                giveback_exit_net_r=0.05,
            )
        )
        self._post_evidence_exit_strict = False

    def print_startup_banner(self) -> None:
        print("=" * 96)
        print("TradingBot V10.9 - FAST ADAPTATION / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Fast entry: first completed 3m direction + 1bp extreme break")
        print("Entry flow: >=20 trades/60s, aligned |imbalance|>=0.05 held 1s")
        print("Intrabar override: slow-EMA reclaim + opposite extreme break")
        print("Override flow: aligned |imbalance|>=0.15 held 2s; no blind flips")
        print("Anti-chase: 12bps normal / 15bps override")
        print("Fast exit: adverse |imbalance|>=0.10 held 2s at <=-0.20R")
        print("Giveback exit: peak >=+0.20R, falls to <=+0.05R with adverse flow")
        print("V10.8 significant targets and realistic cost gate retained")
        print("V10.4 profit guard, hard stop/target, and one position retained")
        print("Daily trade-count cap: OFF; no instant opposite-position flip")
        print("Use runtime_v10_9; all earlier histories remain untouched")
        print("Do not run another TradingBot version at the same time")
        print("=" * 96)

    def _audit_cancel(self, kind: str, prior: Any, reason: str, event_time: int) -> None:
        if prior is None:
            return
        self.policy_audit.record(
            kind,
            reason,
            event_time=int(event_time),
            candle_time=int(prior.candle_time),
            side=str(prior.side),
            details=prior.as_dict(),
        )

    def _cancel_fast_entry(self, reason: str, event_time: int) -> None:
        self._audit_cancel(
            "FAST_ENTRY_WATCH_CANCELLED",
            self.fast_entry_watch.cancel(),
            reason,
            event_time,
        )

    def _cancel_reversal(self, reason: str, event_time: int) -> None:
        self._audit_cancel(
            "FAST_REVERSAL_WATCH_CANCELLED",
            self.reversal_watch.cancel(),
            reason,
            event_time,
        )

    def _disable_slow_actual_entry_paths(self, event_time: int) -> None:
        # V10.9 replaces the actual flat-entry path. Parent diagnostics and
        # shadow candidates remain active, but two-bar/pending entry paths do not.
        self.pending_entry = None
        self._cancel_flow_watch("REPLACED_BY_V10_9", event_time)
        self._cancel_breakout_watch("REPLACED_BY_V10_9", event_time)

    def _allow_intrabar_reversal(
        self,
        base_signal: str,
        snapshot: dict[str, Any],
    ) -> tuple[bool, str]:
        """Extension hook; V10.9 allows the original unrestricted override."""
        return True, "ALLOWED"

    def _uses_v10_9_entry_watches(self) -> bool:
        return True

    async def process_candle(self, candle: dict[str, Any]) -> None:
        decision_time = int(candle["close_time"])
        self._cancel_fast_entry("NEW_COMPLETED_DECISION", decision_time)
        self._cancel_reversal("NEW_COMPLETED_DECISION", decision_time)
        await super().process_candle(candle)

        if self.position_manager.has_position():
            return
        self._disable_slow_actual_entry_paths(decision_time)
        snapshot = dict(self.latest_snapshot)
        signal = str(snapshot.get("signal", "WAIT")).upper()
        eligible = (
            bool(snapshot.get("entry_time_eligible"))
            and snapshot.get("safety_gate") == "PASS"
            and not bool(snapshot.get("data_stale"))
        )
        if not eligible or signal not in {"LONG", "SHORT"}:
            text = f"WAIT | signal={signal} eligible={eligible}; no live entry watch"
            self.signals.status.emit(text)
            self._emit_policy(text)
            return

        atr_value = snapshot.get("atr14")
        atr14 = None if atr_value is None else float(atr_value)
        strict_wait = (
            self._post_evidence_exit_strict
            and self.actual_policy.signal_streak < self.actual_policy.confirmation_bars
        )
        if strict_wait:
            self.policy_audit.record(
                "FAST_ENTRY_SUPPRESSED",
                "POST_EXIT_NEEDS_SECOND_SIGNAL",
                event_time=decision_time,
                candle_time=int(candle["time"]),
                side=signal,
                details={"signal_streak": self.actual_policy.signal_streak},
            )
            self._emit_policy(
                f"{signal} post-exit confirmation {self.actual_policy.signal_streak}/2"
            )
            return

        levels = self._recent_opposing_levels(signal, decision_time)
        fast = self.fast_entry_watch.arm(
            side=signal,
            candle=candle,
            atr14=atr14,
            opposing_levels=levels,
        )
        self.policy_audit.record(
            "FAST_ENTRY_WATCH_ARMED",
            "FIRST_COMPLETED_SIGNAL",
            event_time=decision_time,
            candle_time=fast.candle_time,
            side=fast.side,
            details=fast.as_dict(),
        )

        analysis = self.signal_engine.analyze(self.candle_engine.get_candles())
        slow_ema = analysis.get("slow_ema")
        reversal_allowed, reversal_reason = self._allow_intrabar_reversal(
            signal,
            snapshot,
        )
        if slow_ema is not None and reversal_allowed:
            reverse_side = "LONG" if signal == "SHORT" else "SHORT"
            reversal = self.reversal_watch.arm(
                base_side=signal,
                candle=candle,
                slow_ema=float(slow_ema),
                atr14=atr14,
                opposing_levels=self._recent_opposing_levels(reverse_side, decision_time),
            )
            self.policy_audit.record(
                "FAST_REVERSAL_WATCH_ARMED",
                "STALE_BIAS_OVERRIDE_AVAILABLE",
                event_time=decision_time,
                candle_time=reversal.candle_time,
                side=reversal.side,
                details=reversal.as_dict(),
            )
        elif slow_ema is not None:
            reverse_side = "LONG" if signal == "SHORT" else "SHORT"
            self.policy_audit.record(
                "FAST_REVERSAL_SUPPRESSED",
                reversal_reason,
                event_time=decision_time,
                candle_time=int(candle["time"]),
                side=reverse_side,
                details={
                    "base_signal": signal,
                    "regime": snapshot.get("regime"),
                },
            )
        override_armed = slow_ema is not None and reversal_allowed
        if slow_ema is None:
            reversal_reason = "NO_SLOW_EMA"
        suffix = "override also armed" if override_armed else f"override blocked: {reversal_reason}"
        text = f"{signal} LIVE WATCH | first-signal break + flow; {suffix}"
        self.signals.status.emit(text)
        self._emit_policy(text)

    def _open_fast_position(
        self,
        *,
        state: Any,
        evaluation: Any,
        price: float,
        event_time: int,
        source: str,
        flow: dict[str, Any],
        entry_kind: str,
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
        position["version"] = "10.9"
        position["take_profit"] = evaluation.selected_target_market
        metadata = dict(position.get("metadata", {}))
        metadata["v10_9_fast_entry"] = {
            "kind": entry_kind,
            "watch": state.as_dict(),
            "target_evaluation": evaluation.as_dict(),
            "trigger_flow": dict(flow),
        }
        metadata["v10_5_target_evaluation"] = evaluation.as_dict()
        position["metadata"] = metadata
        self.store.save_position(position)
        self.signals.position.emit(position)
        self.evidence_exit.reset()
        self._post_evidence_exit_strict = False

    def _evaluate_fast_trigger(
        self,
        *,
        state: Any,
        price: float,
        event_time: int,
        source: str,
        flow: dict[str, Any],
        entry_kind: str,
    ) -> None:
        evaluation = self.target_planner.evaluate(
            state.side,
            price,
            self.config,
            atr14=state.atr14,
            opposing_levels=state.opposing_levels,
        )
        event_prefix = "FAST_REVERSAL" if entry_kind == "INTRABAR_REVERSAL" else "FAST_ENTRY"
        if not evaluation.accepted:
            self.policy_audit.record(
                f"{event_prefix}_REJECTED",
                evaluation.reason,
                event_time=event_time,
                candle_time=state.candle_time,
                side=state.side,
                details={
                    "watch": state.as_dict(),
                    "target_evaluation": evaluation.as_dict(),
                    "trigger_flow": flow,
                },
            )
            text = (
                f"{state.side} {entry_kind} rejected: {evaluation.reason} "
                f"room={evaluation.room_bps:.1f}bps net={evaluation.estimated_net_reward_r:+.2f}R"
            )
            self.signals.status.emit(text)
            self._emit_policy(text)
            return
        self._open_fast_position(
            state=state,
            evaluation=evaluation,
            price=price,
            event_time=event_time,
            source=source,
            flow=flow,
            entry_kind=entry_kind,
        )
        self.policy_audit.record(
            f"{event_prefix}_ACCEPTED",
            evaluation.target_source,
            event_time=event_time,
            candle_time=state.candle_time,
            side=state.side,
            details={
                "watch": state.as_dict(),
                "target_evaluation": evaluation.as_dict(),
                "trigger_flow": flow,
            },
        )
        text = (
            f"{state.side} {entry_kind} OPEN | room={evaluation.room_bps:.1f}bps "
            f"net={evaluation.estimated_net_reward_r:+.2f}R"
        )
        print(f"[V10.9] {text}", flush=True)
        self._emit_policy(text)

    def _observe_entry_watch(
        self,
        *,
        watch: Any,
        price: float,
        event_time: int,
        source: str,
        flow: dict[str, Any],
        entry_kind: str,
    ) -> bool:
        state = watch.state
        if state is None:
            return False
        observation = watch.observe(
            price=price,
            event_time=event_time,
            trade_count_60s=int(flow.get("trade_count_60s") or 0),
            flow_imbalance_60s=float(flow.get("flow_imbalance_60s") or 0.0),
        )
        if observation.cancel:
            prior = watch.cancel()
            kind = (
                "FAST_REVERSAL_WATCH_CANCELLED"
                if entry_kind == "INTRABAR_REVERSAL"
                else "FAST_ENTRY_WATCH_CANCELLED"
            )
            self._audit_cancel(kind, prior, observation.reason, event_time)
            return False
        if observation.status == "CONFIRMING":
            self._emit_policy(
                f"{state.side} {entry_kind} CONFIRMING | "
                f"flow={float(flow.get('flow_imbalance_60s') or 0.0):+.3f}"
            )
        if not observation.trigger:
            return False
        consumed = watch.cancel()
        if consumed is None:
            return False
        self._evaluate_fast_trigger(
            state=consumed,
            price=price,
            event_time=event_time,
            source=source,
            flow=flow,
            entry_kind=entry_kind,
        )
        return self.position_manager.has_position()

    def _apply_fast_evidence_exit(
        self,
        trade: dict[str, Any],
        flow: dict[str, Any],
    ) -> bool:
        position = self.position_manager.get_position()
        if position is None:
            self.evidence_exit.reset()
            return False
        event_time = int(trade["event_time"])
        if event_time <= int(position["entry_event_time"]):
            return False
        price = float(trade["price"])
        updated = self.position_manager.update_unrealized_pnl(price)
        if updated is None:
            return False
        observation = self.evidence_exit.observe(
            position=updated,
            event_time=event_time,
            trade_count_60s=int(flow.get("trade_count_60s") or 0),
            flow_imbalance_60s=float(flow.get("flow_imbalance_60s") or 0.0),
        )
        if not observation.trigger:
            if observation.status == "CONFIRMING":
                self._emit_policy(f"EVIDENCE EXIT CONFIRMING | {observation.reason}")
            return False
        if bool(trade.get("entry_eligible", False)):
            self.path_tracker.observe(price, event_time)
        snapshot = self.evidence_exit.snapshot()
        closed = self.position_manager.close_position(
            price,
            "EVIDENCE FAILURE",
            event_time,
            str(trade.get("source", "UNKNOWN")),
        )
        if closed is None:
            return False
        metadata = dict(closed.get("metadata", {}))
        metadata["v10_9_evidence_exit"] = {
            "reason": observation.reason,
            "guard": snapshot,
            "flow": dict(flow),
        }
        closed["metadata"] = metadata
        self._record_closed_trade(closed)
        genuine_directional_loss = observation.reason == "LOSS_EVIDENCE_CONFIRMED"
        if genuine_directional_loss:
            self.actual_policy.mark_signal_exit()
        self._post_evidence_exit_strict = genuine_directional_loss
        self.policy_audit.record(
            "EVIDENCE_EXIT",
            observation.reason,
            event_time=event_time,
            candle_time=None,
            side=str(position["position"]),
            details={"guard": snapshot, "flow": flow, "price": price},
        )
        if genuine_directional_loss:
            self._emit_policy("FLAT after genuine adverse move; next entry needs 2 signals")
        else:
            self._emit_policy("FLAT after profit giveback; immediate continuation watch allowed")
        return True

    async def handle_trade_event(self, trade: dict[str, Any]) -> None:
        had_position_before_parent = self.position_manager.has_position()
        await super().handle_trade_event(trade)
        event_time = int(trade["event_time"])
        flow = self.order_flow.snapshot(event_time)
        if self.position_manager.has_position():
            self._cancel_fast_entry("POSITION_ALREADY_OPEN", event_time)
            self._cancel_reversal("POSITION_ALREADY_OPEN", event_time)
            self._apply_fast_evidence_exit(trade, flow)
            return
        if had_position_before_parent:
            # A parent stop/target/profit-guard exit must not turn into a same-
            # print opposite entry. Re-entry starts with later evidence.
            self._cancel_fast_entry("POSITION_CLOSED_THIS_PRINT", event_time)
            self._cancel_reversal("POSITION_CLOSED_THIS_PRINT", event_time)
            return
        if not bool(trade.get("entry_eligible", False)):
            return
        price = float(trade["price"])
        source = str(trade.get("source", "UNKNOWN"))
        if self._observe_entry_watch(
            watch=self.fast_entry_watch,
            price=price,
            event_time=event_time,
            source=source,
            flow=flow,
            entry_kind="FIRST_SIGNAL",
        ):
            self._cancel_reversal("FAST_ENTRY_OPENED", event_time)
            return
        if self._observe_entry_watch(
            watch=self.reversal_watch,
            price=price,
            event_time=event_time,
            source=source,
            flow=flow,
            entry_kind="INTRABAR_REVERSAL",
        ):
            self._cancel_fast_entry("FAST_REVERSAL_OPENED", event_time)
            return
        if (
            self._uses_v10_9_entry_watches()
            and
            self.fast_entry_watch.state is None
            and self.reversal_watch.state is None
            and not self.position_manager.has_position()
        ):
            text = "WAIT | live entry watches expired or were invalidated"
            self.signals.status.emit(text)
            self._emit_policy(text)

    def _record_closed_trade(self, trade: dict[str, Any] | None) -> None:
        if trade is None:
            return
        reason = str(trade.get("reason", ""))
        super()._record_closed_trade(trade)
        self.evidence_exit.reset()
        if reason == "SIGNAL TO NEUTRAL":
            self._post_evidence_exit_strict = True

    async def stop(self) -> None:
        now = int(time.time() * 1000)
        self._cancel_fast_entry("SHUTDOWN", now)
        self._cancel_reversal("SHUTDOWN", now)
        await super().stop()


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_9.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.9 already running",
            "Another V10.9 instance already owns this project. Close it first.",
        )
        return 2
    window = TradingWindowV10_9()
    window.showMaximized()
    bot = TradingBotV10_9(window)
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
