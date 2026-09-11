"""TradingBot V10.10: completed-1m decisions with live-trade execution."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp
from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox

from core.fast_adaptation_v10_9 import (
    FastInitialEntryConfigV10_9,
    FastInitialEntryWatchV10_9,
)
from core.micro_decision_v10_10 import (
    AggregateTradeOneMinuteBarsV10_10,
    OneMinuteSignalEngineV10_10,
    context_requirement,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_8 import TradingBotV10_8
from terminal_v10_9_2 import TradingBotV10_9_2, TradingWindowV10_9_2


class TradingWindowV10_10(TradingWindowV10_9_2):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.10 - ONE-MINUTE ADAPTIVE EXECUTION")
        self.title_label.setText(
            "TradingBot V10.10 - ONE-MINUTE ADAPTIVE EXECUTION / PAPER ONLY"
        )
        self.policy_label.setText(
            "V10.10 Policy: WARMUP | loading completed 1m history"
        )
        self.update_signal("WAIT")
        for label in self.findChildren(QLabel):
            if label.text() == "XAUUSDT · 3-minute chart":
                label.setText("XAUUSDT · 3m context chart · entries use completed 1m")

    def update_policy(self, text: str) -> None:
        self.policy_label.setText(f"V10.10 Policy: {text}")

    def update_signal(self, signal: str) -> None:
        # Preserve V10.4's direction colors, then make the clock explicit.
        clean = str(signal).replace("1m ", "")
        super().update_signal(clean)
        self.signal_label.setText(f"Closed 1m Signal: {clean}")


class TradingBotV10_10(TradingBotV10_9_2):
    runtime_name = "runtime_v10_10"
    micro_log_version = "V10.10"

    def __init__(self, window: TradingWindowV10_10) -> None:
        super().__init__(window)
        self.micro_bars = AggregateTradeOneMinuteBarsV10_10(maximum_bars=500)
        self.micro_engine = OneMinuteSignalEngineV10_10()
        self.micro_entry_watch = FastInitialEntryWatchV10_9()
        self.micro_signal = "WAIT"
        self.micro_reason = "Waiting for completed 1m bar"
        self.micro_last_signal = "WAIT"
        self.micro_signal_streak = 0
        self.micro_history_seeded = False
        self.signals.signal.emit("WAIT")
        self.signals.signal_reason.emit("Waiting for first completed 1m decision")
        self.signals.status.emit("V10.10 ready | waiting for first completed 1m decision")
        self._emit_policy("READY | waiting for first completed 1m decision")

    def _uses_v10_9_entry_watches(self) -> bool:
        return False

    def _uses_v10_7_flow_watch(self) -> bool:
        return False

    def print_startup_banner(self) -> None:
        print("=" * 98)
        print("TradingBot V10.10 - ONE-MINUTE ADAPTIVE EXECUTION / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Decision clock: genuine completed 1m bars; REST seed + live aggTrades")
        print("Same/aligned context: first 1m signal + 0.05-0.08 flow confirmation")
        print("Against 3m trend: 2 consecutive 1m signals + |flow|>=0.15")
        print("Entry: 0.5bp 1m-extreme break, 0.5s hold, 10bp anti-chase")
        print("Exit: opposite completed 1m signal + aligned |flow|>=0.08")
        print("V10.9.1 cost-aware evidence exit and V10.8 target gate retained")
        print("Daily trade-count cap: OFF; one paper position; no same-print flip")
        print("runtime=runtime_v10_10; do not run another bot version concurrently")
        print("=" * 98)

    async def _seed_micro_history(self) -> None:
        timeout = aiohttp.ClientTimeout(total=15, connect=10, sock_connect=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                params = {"symbol": "XAUUSDT", "interval": "1m", "limit": 200}
                async with session.get(self.market_data.rest_url, params=params) as response:
                    response.raise_for_status()
                    rows = await response.json()
            now_ms = int(time.time() * 1000)
            candles = [
                {
                    "time": int(row[0]),
                    "close_time": int(row[6]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "trade_count": int(row[8]),
                    "closed": True,
                    "source": "REST_1M_SEED",
                }
                for row in rows
                if int(row[6]) < now_ms
            ]
            self.micro_bars.seed(candles)
            self.micro_history_seeded = bool(candles)
            print(
                f"[{self.micro_log_version}] Seeded {len(candles)} completed 1m bars",
                flush=True,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError) as exc:
            self.micro_history_seeded = False
            print(
                f"[{self.micro_log_version}] 1m REST seed unavailable ({type(exc).__name__}); "
                "live warmup will be required",
                flush=True,
            )

    async def start(self) -> None:
        await self._seed_micro_history()
        await super().start()

    async def process_candle(self, candle: dict[str, Any]) -> None:
        # Retain 3m diagnostics/regime/structure, but disable every inherited
        # actual entry path. V10.10's only actual entry clock is completed 1m.
        await TradingBotV10_8.process_candle(self, candle)
        event_time = int(candle["close_time"])
        self._disable_slow_actual_entry_paths(event_time)
        self._cancel_fast_entry("REPLACED_BY_V10_10", event_time)
        self._cancel_reversal("REPLACED_BY_V10_10", event_time)
        self.signals.signal.emit(self.micro_signal)
        self.signals.signal_reason.emit(self.micro_reason)

    def _set_micro_streak(self, signal: str) -> None:
        if signal in {"LONG", "SHORT"} and signal == self.micro_last_signal:
            self.micro_signal_streak += 1
        elif signal in {"LONG", "SHORT"}:
            self.micro_last_signal = signal
            self.micro_signal_streak = 1
        else:
            self.micro_last_signal = "WAIT"
            self.micro_signal_streak = 0

    def _cancel_micro_watch(self, reason: str, event_time: int) -> None:
        prior = self.micro_entry_watch.cancel()
        if prior is None:
            return
        self.policy_audit.record(
            "MICRO_ENTRY_WATCH_CANCELLED",
            reason,
            event_time=int(event_time),
            candle_time=prior.candle_time,
            side=prior.side,
            details=prior.as_dict(),
        )

    def _micro_flow_aligned(
        self,
        side: str,
        flow: dict[str, Any],
        threshold: float,
    ) -> bool:
        if int(flow.get("trade_count_60s") or 0) < 20:
            return False
        imbalance = float(flow.get("flow_imbalance_60s") or 0.0)
        return imbalance >= threshold if side == "LONG" else imbalance <= -threshold

    def _close_on_micro_invalidation(
        self,
        bar: dict[str, Any],
        decision,
        trade: dict[str, Any],
        flow: dict[str, Any],
    ) -> bool:
        position = self.position_manager.get_position()
        if position is None or decision.signal not in {"LONG", "SHORT"}:
            return False
        current_side = str(position["position"])
        if decision.signal == current_side:
            return False
        if not bool(trade.get("entry_eligible", False)):
            return False
        if not self._micro_flow_aligned(decision.signal, flow, 0.08):
            self.policy_audit.record(
                "MICRO_EXIT_SUPPRESSED",
                "OPPOSITE_1M_FLOW_NOT_ALIGNED",
                event_time=int(trade["event_time"]),
                candle_time=int(bar["time"]),
                side=current_side,
                details={"micro_signal": decision.signal, "flow": flow},
            )
            return False
        price = float(trade["price"])
        event_time = int(trade["event_time"])
        closed = self.position_manager.close_position(
            price,
            "1M INVALIDATION",
            event_time,
            str(trade.get("source", "UNKNOWN")),
        )
        self._record_closed_trade(closed)
        self._cancel_micro_watch("POSITION_CLOSED", event_time)
        self.policy_audit.record(
            "MICRO_EXIT",
            "OPPOSITE_1M_WITH_FLOW",
            event_time=event_time,
            candle_time=int(bar["time"]),
            side=current_side,
            details={"micro_signal": decision.signal, "flow": flow},
        )
        self._emit_policy("FLAT after opposite completed 1m signal; no same-print flip")
        return True

    def _on_completed_micro_bar(
        self,
        bar: dict[str, Any],
        trade: dict[str, Any],
        flow: dict[str, Any],
    ) -> bool:
        self._cancel_micro_watch("NEW_COMPLETED_1M_DECISION", int(bar["close_time"]))
        decision = self.micro_engine.analyze(self.micro_bars.candles())
        self.micro_signal = decision.signal
        self.micro_reason = decision.reason
        self._set_micro_streak(decision.signal)
        self.signals.signal.emit(decision.signal)
        self.signals.signal_reason.emit(decision.reason)
        regime = str(self.latest_snapshot.get("regime") or "UNKNOWN")
        self.policy_audit.record(
            "MICRO_DECISION",
            decision.reason,
            event_time=int(bar["close_time"]),
            candle_time=int(bar["time"]),
            side=decision.signal if decision.signal in {"LONG", "SHORT"} else None,
            details={
                "regime_3m": regime,
                "signal_streak": self.micro_signal_streak,
                "fast_ema": decision.fast_ema,
                "slow_ema": decision.slow_ema,
                "atr14_1m": decision.atr14,
                "gap_atr": decision.gap_atr,
                "flow": flow,
            },
        )
        print(
            f"[{self.micro_log_version} 1M] close={int(bar['close_time'])} "
            f"signal={decision.signal} regime3m={regime} "
            f"streak={self.micro_signal_streak} reason={decision.reason}",
            flush=True,
        )

        if self._close_on_micro_invalidation(bar, decision, trade, flow):
            return True
        if self.position_manager.has_position():
            self._emit_policy(f"HOLD | 1m={decision.signal} 3m regime={regime}")
            return False
        if decision.signal not in {"LONG", "SHORT"}:
            text = f"WAIT 1m | {decision.reason}"
            self.signals.status.emit(text)
            self._emit_policy(text)
            return False

        required_streak, flow_threshold, context = context_requirement(
            decision.signal,
            regime,
        )
        if self.micro_signal_streak < required_streak:
            text = (
                f"{decision.signal} 1m {context} | confirmation "
                f"{self.micro_signal_streak}/{required_streak}"
            )
            self.signals.status.emit(text)
            self._emit_policy(text)
            return False

        snapshot = dict(self.latest_snapshot)
        trade_age = flow.get("trade_age_ms")
        flow_fresh = trade_age is not None and int(trade_age) <= self.hard_trade_staleness_ms
        daily_safety = self._daily_safety(int(bar["close_time"]))
        eligible = (
            bool(trade.get("entry_eligible", False))
            and flow_fresh
            and not bool(daily_safety.get("daily_loss_blocked"))
        )
        if not eligible:
            self.policy_audit.record(
                "MICRO_ENTRY_SUPPRESSED",
                "LIVE_SAFETY_NOT_READY",
                event_time=int(trade["event_time"]),
                candle_time=int(bar["time"]),
                side=decision.signal,
                details={
                    "entry_eligible": bool(trade.get("entry_eligible", False)),
                    "flow_fresh": flow_fresh,
                    "trade_age_ms": trade_age,
                    "daily_safety": daily_safety,
                },
            )
            text = f"{decision.signal} 1m blocked: live trade/safety state not ready"
            self.signals.status.emit(text)
            self._emit_policy(text)
            return False

        self.micro_entry_watch = FastInitialEntryWatchV10_9(
            FastInitialEntryConfigV10_9(
                lifetime_ms=60_000,
                break_buffer_bps=0.5,
                confirmation_ms=500,
                minimum_trade_count_60s=20,
                minimum_abs_flow_imbalance=flow_threshold,
                maximum_chase_bps=10.0,
            )
        )
        target_atr = snapshot.get("atr14")
        if target_atr is None and decision.atr14 is not None:
            # Causal startup fallback until the first live 3m context closes.
            # sqrt(3) scales one-minute volatility without inventing future bars.
            target_atr = float(decision.atr14) * (3.0 ** 0.5)
        state = self.micro_entry_watch.arm(
            side=decision.signal,
            candle=bar,
            atr14=None if target_atr is None else float(target_atr),
            opposing_levels=self._recent_opposing_levels(
                decision.signal,
                int(bar["close_time"]),
            ),
        )
        self.policy_audit.record(
            "MICRO_ENTRY_WATCH_ARMED",
            context,
            event_time=int(bar["close_time"]),
            candle_time=int(bar["time"]),
            side=decision.signal,
            details={
                "watch": state.as_dict(),
                "required_streak": required_streak,
                "flow_threshold": flow_threshold,
                "regime_3m": regime,
            },
        )
        text = (
            f"{decision.signal} 1m LIVE WATCH | {context} | "
            f"flow>={flow_threshold:.2f}"
        )
        print(f"[{self.micro_log_version} 1M] {text}", flush=True)
        self.signals.status.emit(text)
        self._emit_policy(text)
        return False

    def _open_fast_position(self, **kwargs: Any) -> None:
        super()._open_fast_position(**kwargs)
        position = self.position_manager.get_position()
        if position is None:
            return
        position["version"] = "10.10"
        metadata = dict(position.get("metadata", {}))
        metadata["v10_10_one_minute_entry"] = metadata.get("v10_9_fast_entry", {})
        position["metadata"] = metadata
        self.store.save_position(position)
        self.signals.position.emit(position)

    async def handle_trade_event(self, trade: dict[str, Any]) -> None:
        had_position = self.position_manager.has_position()
        await super().handle_trade_event(trade)
        event_time = int(trade["event_time"])
        completed = self.micro_bars.update(trade)
        flow = self.order_flow.snapshot(event_time)
        if had_position and not self.position_manager.has_position():
            self._cancel_micro_watch("POSITION_CLOSED_THIS_PRINT", event_time)
            return
        for bar in completed:
            if self._on_completed_micro_bar(bar, trade, flow):
                return
        if self.position_manager.has_position() or not bool(trade.get("entry_eligible", False)):
            return
        state = self.micro_entry_watch.state
        if state is None:
            return
        if self._observe_entry_watch(
            watch=self.micro_entry_watch,
            price=float(trade["price"]),
            event_time=event_time,
            source=str(trade.get("source", "UNKNOWN")),
            flow=flow,
            entry_kind="1M_DIRECTION",
        ):
            return
        if self.micro_entry_watch.state is None:
            text = "WAIT 1m | entry watch expired, invalidated, or rejected"
            self.signals.status.emit(text)
            self._emit_policy(text)

    async def stop(self) -> None:
        self._cancel_micro_watch("SHUTDOWN", int(time.time() * 1000))
        await super().stop()


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_10.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.10 already running",
            "Another V10.10 instance already owns this project. Close it first.",
        )
        return 2
    window = TradingWindowV10_10()
    window.showMaximized()
    bot = TradingBotV10_10(window)
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
