"""TradingBot V10.12: early persistent-flow entry after completed 1m direction."""

from __future__ import annotations

import sys
import time
import asyncio
import inspect
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox, QLabel

from core.early_flow_entry_v10_12 import (
    EarlyFlowEntryConfigV10_12,
    EarlyFlowEntryWatchV10_12,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_11 import TradingBotV10_11, TradingWindowV10_11
from core.target_comparison_v10_12 import (
    ResearchWindow, TargetComparisonV10_12, UncappedTargetPlannerV10_12,
)


class TargetComparisonSignals(QObject):
    updated = pyqtSignal(dict)


class TradingWindowV10_12(TradingWindowV10_11):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.12 - EARLY FLOW ENTRY")
        self.title_label.setText(
            "TradingBot V10.12 - EARLY FLOW ENTRY / PAPER ONLY"
        )
        self.policy_label.setText(
            "V10.12 Policy: WARMUP | loading completed 1m history"
        )
        self.target_comparison_label = QLabel(
            "Target test: SHADOW ONLY | baseline versus no ATR cap | waiting for feed"
        )
        self.target_comparison_label.setWordWrap(True)
        self.layout.insertWidget(3, self.target_comparison_label)

    def update_target_comparison(self, data: dict[str, Any]) -> None:
        parts = []
        for mode, item in data["portfolios"].items():
            parts.append(f"{mode}: {item['trades']} closed, net=${item['net']:+.2f}, "
                         f"open={item['open']}, unreal=${item['unrealized']:+.2f}")
        state = "FAILED — check verifier" if data["failed"] else "SHADOW ONLY"
        self.target_comparison_label.setText(
            f"Target test: {state} | " + " | ".join(parts) + " | actual policy unchanged"
        )

    def update_policy(self, text: str) -> None:
        self.policy_label.setText(f"V10.12 Policy: {text}")


class TradingBotV10_12(TradingBotV10_11):
    runtime_name = "runtime_v10_12"
    micro_log_version = "V10.12"
    diagnostic_revision = "EARLY_FLOW_INTEGRITY_1"
    enable_target_comparison = True
    target_policy_mode = "BASELINE"

    def __init__(self, window: TradingWindowV10_12) -> None:
        super().__init__(window)
        self.target_comparison = None
        self._comparison_lock = None
        self._comparison_last_emit = 0.0
        if self.target_policy_mode == "NO_ATR_CAP":
            self.target_planner = UncappedTargetPlannerV10_12(self.target_config)
        self.policy_audit.record(
            "EARLY_FLOW_REVISION", self.diagnostic_revision,
            event_time=int(time.time() * 1000),
            details={"execution": asdict(self.config), "target": asdict(self.target_config),
                     "daily_loss_gate_enabled": self.daily_loss_gate_enabled,
                     "daily_loss_percent": self.daily_loss_percent,
                     "execution_freshness_ms": self.market_data.rest_execution_freshness_ms,
                     "target_policy_mode": self.target_policy_mode},
        )
        if self.enable_target_comparison:
            self.comparison_signals = TargetComparisonSignals()
            self.comparison_signals.updated.connect(window.update_target_comparison)
            root = Path(__file__).resolve().parent / self.runtime_name / "target_comparison_v1"

            def factory(runtime, mode):
                # Same engine and callback sequence as actual, independent ledgers.
                # Never call start(): only the actual bot owns the network feed.
                cls = type(f"Research_{mode}", (TradingBotV10_12,), {
                    "runtime_name": str(runtime), "enable_target_comparison": False,
                    "target_policy_mode": mode, "micro_log_version": f"SHADOW {mode}",
                    "print_startup_banner": lambda self: None,
                })
                return cls(ResearchWindow())

            self.target_comparison = TargetComparisonV10_12(root, factory, self.policy_audit)
            self._emit_target_comparison(force=True)

    def _emit_target_comparison(self, *, force=False) -> None:
        comparison = self.target_comparison
        if comparison is None:
            return
        now = time.monotonic()
        if not force and now - self._comparison_last_emit < 1.0:
            return
        self._comparison_last_emit = now
        self.comparison_signals.updated.emit({
            "failed": comparison.failed,
            "portfolios": {mode: {
                "trades": p.total_trades, "net": p.position_manager.realized_net_pnl,
                "open": p.position_manager.has_position(),
                "unrealized": p.position_manager.get_unrealized_pnl(),
            } for mode, p in comparison.portfolios.items()},
        })

    def market_callbacks(self) -> dict[str, Any]:
        callbacks = super().market_callbacks()
        if self.target_comparison is None:
            return callbacks
        for name in TargetComparisonV10_12.forwarded:
            actual = callbacks[name]

            async def forward(*args, _name=name, _actual=actual, **kwargs):
                if self._comparison_lock is None:
                    self._comparison_lock = asyncio.Lock()
                async with self._comparison_lock:
                    if _name == "trade_callback":
                        args = ({**args[0], "_received_at_ms": int(time.time() * 1000)}, *args[1:])
                    result = _actual(*args, **kwargs)
                    if inspect.isawaitable(result):
                        result = await result
                    await self.target_comparison.dispatch(_name, *args, **kwargs)
                    self._emit_target_comparison()
                    return result

            callbacks[name] = forward
        return callbacks

    async def _seed_micro_history(self) -> None:
        await super()._seed_micro_history()
        if self.target_comparison is not None:
            self.target_comparison.seed(self.micro_bars.candles())

    def _recent_opposing_levels(self, side: str, decision_time: int) -> tuple[float, ...]:
        levels = super()._recent_opposing_levels(side, decision_time)
        self.policy_audit.record(
            "TARGET_STRUCTURE_SELECTION", "LEVELS_AVAILABLE" if levels else "NO_SIGNIFICANT_LEVELS",
            event_time=int(decision_time), side=side,
            details={"levels": list(levels), "clusters": self.significant_selector.last_diagnostics,
                     "target_policy_mode": self.target_policy_mode},
        )
        return levels

    async def stop(self) -> None:
        # Close research ledgers while the owning audit store remains available.
        try:
            if self.target_comparison is not None:
                await self.market_data.stop()
                await self.target_comparison.stop()
        finally:
            await super().stop()

    async def handle_trade_event(self, trade: dict[str, Any]) -> None:
        # Recheck at consumption: the feed's eligibility flag was calculated
        # before awaiting its callback. Keep replay paths available for exits.
        trade = dict(trade)
        now_ms = int(trade.get("_received_at_ms", time.time() * 1000))
        event_time = int(trade["event_time"])
        trade["entry_eligible"] = bool(trade.get("entry_eligible", False)) and (
            self.market_data._rest_trade_is_execution_fresh(
                event_time, self.market_data.rest_execution_freshness_ms, now_ms=now_ms,
            )
        )
        self._early_receipt_age_ms = now_ms - event_time
        watch = self.micro_entry_watch
        if isinstance(watch, EarlyFlowEntryWatchV10_12) and watch.state is not None:
            if not trade["entry_eligible"]:
                watch.reset_confirmation()
                self._audit_early_observation(watch, "WAIT", "INELIGIBLE_TRADE_RESET", trade)
                if event_time > watch.state.expiry_time or now_ms > watch.state.expiry_time:
                    self._cancel_micro_watch("EXPIRED_DURING_STALE_DATA", event_time)
        await super().handle_trade_event(trade)

    def _audit_early_observation(self, watch, status, reason, trade, flow=None) -> None:
        key = (status, reason)
        if watch.last_audit_key == key:
            return
        watch.last_audit_key = key
        state = watch.state
        self.policy_audit.record(
            "EARLY_FLOW_OBSERVATION", reason,
            event_time=int(trade["event_time"]), candle_time=state.candle_time,
            side=state.side,
            details={
                "revision": self.diagnostic_revision, "status": status,
                "watch": state.as_dict(), "diagnostics": watch.diagnostics(),
                "market_price": float(trade["price"]),
                "flow": flow,
                "receipt_age_ms": getattr(self, "_early_receipt_age_ms", None),
                "decision_to_observation_ms": int(trade["event_time"]) - state.decision_time,
            },
        )

    def _observe_entry_watch(self, **kwargs: Any) -> bool:
        watch = kwargs["watch"]
        if not isinstance(watch, EarlyFlowEntryWatchV10_12) or watch.state is None:
            return super()._observe_entry_watch(**kwargs)
        state = watch.state
        flow = dict(kwargs["flow"])
        if kwargs["event_time"] + getattr(self, "_early_receipt_age_ms", 0) > state.expiry_time:
            self._cancel_micro_watch("EXPIRED_AT_CONSUMPTION", kwargs["event_time"])
            text = f"{state.side} EARLY FLOW CANCELLED: EXPIRED_AT_CONSUMPTION"
            self.signals.status.emit(text)
            self._emit_policy(text)
            return True
        observation = watch.observe(
            price=kwargs["price"], event_time=kwargs["event_time"],
            trade_count_60s=int(flow.get("trade_count_60s") or 0),
            flow_imbalance_60s=float(flow.get("flow_imbalance_60s") or 0.0),
            flow_trades=self.order_flow.trades,
        )
        self._audit_early_observation(watch, observation.status, observation.reason, {
            "event_time": kwargs["event_time"], "price": kwargs["price"],
        }, flow=flow)
        if observation.cancel:
            self._cancel_micro_watch(observation.reason, kwargs["event_time"])
            text = f"{state.side} EARLY FLOW CANCELLED: {observation.reason}"
            self.signals.status.emit(text)
            self._emit_policy(text)
            # This result was handled, including its terminal UI message.
            return True
        if observation.trigger:
            flow["v10_12_diagnostics"] = {
                **watch.diagnostics(), "revision": self.diagnostic_revision,
                "receipt_age_ms": getattr(self, "_early_receipt_age_ms", None),
                "decision_to_trigger_ms": kwargs["event_time"] - state.decision_time,
            }
            consumed = watch.cancel()
            self._evaluate_fast_trigger(
                state=consumed, price=kwargs["price"], event_time=kwargs["event_time"],
                source=kwargs["source"], flow=flow, entry_kind=kwargs["entry_kind"],
            )
            # V10.10 must not overwrite a specific economic rejection with WAIT.
            return True
        self._emit_policy(f"{state.side} EARLY FLOW {observation.status} | {observation.reason}")
        return False

    def _cancel_micro_watch(self, reason: str, event_time: int) -> None:
        watch = self.micro_entry_watch
        if isinstance(watch, EarlyFlowEntryWatchV10_12) and watch.state is not None:
            self.policy_audit.record(
                "EARLY_FLOW_WATCH_CANCELLED", reason, event_time=int(event_time),
                candle_time=watch.state.candle_time, side=watch.state.side,
                details={"watch": watch.state.as_dict(), "diagnostics": watch.diagnostics(),
                         "revision": self.diagnostic_revision},
            )
        super()._cancel_micro_watch(reason, event_time)

    def _on_completed_micro_bar(
        self,
        bar: dict[str, Any],
        trade: dict[str, Any],
        flow: dict[str, Any],
    ) -> bool:
        handled = super()._on_completed_micro_bar(bar, trade, flow)
        if handled or self.position_manager.has_position():
            return handled
        prior = self.micro_entry_watch.state
        if prior is None:
            return handled

        threshold = float(self.micro_entry_watch.config.minimum_abs_flow_imbalance)
        early = EarlyFlowEntryWatchV10_12(
            EarlyFlowEntryConfigV10_12(
                lifetime_ms=10_000,
                confirmation_ms=500,
                minimum_trade_count_60s=20,
                minimum_abs_flow_imbalance=threshold,
                maximum_chase_bps=5.0,
            )
        )
        self.micro_entry_watch = early
        state = early.arm_from(prior)
        self.policy_audit.record(
            "EARLY_FLOW_WATCH_ARMED",
            "NO_SECOND_EXTREME_BREAK",
            event_time=int(bar["close_time"]),
            candle_time=int(bar["time"]),
            side=state.side,
            details={"watch": state.as_dict(), "flow_threshold": threshold,
                     "revision": self.diagnostic_revision,
                     "armed_on_event_time": int(trade["event_time"])},
        )
        text = (
            f"{state.side} EARLY FLOW WATCH | hold=0.5s "
            f"flow>={threshold:.2f} max-chase=5bps"
        )
        print(f"[V10.12 1M] {text}", flush=True)
        self.signals.status.emit(text)
        self._emit_policy(text)
        return handled

    def _open_fast_position(self, **kwargs: Any) -> None:
        super()._open_fast_position(**kwargs)
        position = self.position_manager.get_position()
        if position is None:
            return
        position["version"] = "10.12"
        metadata = dict(position.get("metadata", {}))
        metadata["target_policy_mode"] = self.target_policy_mode
        metadata["v10_12_early_flow_entry"] = metadata.get(
            "v10_10_one_minute_entry", {}
        )
        position["metadata"] = metadata
        self.store.save_position(position)
        self.signals.position.emit(position)

    def print_startup_banner(self) -> None:
        print("=" * 100)
        print("TradingBot V10.12 - EARLY FLOW ENTRY / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Direction: genuine completed 1m decision; 3m is causal context")
        print("Entry: persistent aligned flow for 0.5s; no second extreme break")
        print("Entry watch: 10s; cancel when move is already >5bps chased")
        print("Countertrend still requires 2 completed 1m signals + |flow|>=0.15")
        print("V10.11 confirmed-structure fallback and economic gates retained")
        print("Realistic costs retained; one position; daily trade-count cap OFF")
        print(f"Daily-loss gate: {'ENFORCED' if self.daily_loss_gate_enabled else 'SHADOW ONLY'}")
        print(f"Diagnostics: {self.diagnostic_revision}; rolling-window continuity checked")
        print("Target comparison: SHADOW ONLY; independent baseline / no-ATR-cap portfolios")
        print("runtime=runtime_v10_12; do not combine with earlier runtimes")
        print("=" * 100)


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_12.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.12 already running",
            "Another V10.12 instance already owns this project. Close it first.",
        )
        return 2
    window = TradingWindowV10_12()
    window.showMaximized()
    bot = TradingBotV10_12(window)
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
