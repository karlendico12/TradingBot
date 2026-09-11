"""TradingBot V10.2: current Binance feeds plus independent shadow outcomes.

The V9 EMA signal and the actual V10 paper portfolio remain unchanged. V10.2
hardens data/execution integrity and labels every timely signal independently so
future strategy changes can be evaluated without contaminating this run.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox

from core.shadow_outcomes_v10_2 import (
    ShadowConfigV10_2,
    ShadowOutcomeEngineV10_2,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_1 import TradingBotV10_1, TradingWindowV10_1


class ShadowSignalsV10_2(QObject):
    updated = pyqtSignal(dict)


class TradingWindowV10_2(TradingWindowV10_1):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.2 - INTEGRITY + SHADOW PAPER")
        self.title_label.setText("TradingBot V10.2 - INTEGRITY + SHADOW PAPER")
        self.feed_health_label = QLabel("Feed Health: WARMUP")
        self.shadow_label = QLabel("Shadow Outcomes: WARMUP")
        chart_index = self.layout.indexOf(self.chart)
        self.layout.insertWidget(chart_index, self.feed_health_label)
        self.layout.insertWidget(chart_index + 1, self.shadow_label)

    @staticmethod
    def _age(value: Any) -> str:
        return "--" if value is None else f"{float(value):.1f}s"

    def update_diagnostics(self, snapshot: dict[str, Any]) -> None:
        super().update_diagnostics(snapshot)
        self.safety_label.setText(
            self.safety_label.text()
            + " | daily gate="
            + ("ENABLED" if snapshot.get("daily_loss_gate_enabled") else "SHADOW")
        )
        market = "UP" if snapshot.get("market_ws_connected") else "DOWN"
        public = "UP" if snapshot.get("public_ws_connected") else "DOWN"
        self.feed_health_label.setText(
            "Feed Health: "
            f"marketWS={market} publicWS={public} | "
            f"kline={self._age(snapshot.get('kline_ws_age_s'))} "
            f"trades={self._age(snapshot.get('agg_trade_ws_age_s'))} "
            f"book={self._age(snapshot.get('book_ws_age_s'))} | "
            f"REST bars={int(snapshot.get('rest_candles_recovered', 0) or 0)} "
            f"trades={int(snapshot.get('rest_trades_recovered', 0) or 0)}"
        )

    def update_shadow(self, stats: dict[str, Any]) -> None:
        mean_r = stats.get("mean_r")
        pf = stats.get("profit_factor")
        mean_text = "--" if mean_r is None else f"{float(mean_r):+.3f}R"
        pf_text = "--" if pf is None else f"{float(pf):.2f}"
        self.shadow_label.setText(
            "Shadow Outcomes: "
            f"candidates={int(stats.get('candidates', 0))} "
            f"pending={int(stats.get('pending', 0))} "
            f"open={int(stats.get('open', 0))} "
            f"closed={int(stats.get('closed', 0))} | "
            f"mean={mean_text} PF={pf_text}"
        )


class TradingBotV10_2(TradingBotV10_1):
    runtime_name = "runtime_v10_2"

    def __init__(self, window: TradingWindowV10_2) -> None:
        super().__init__(window, runtime_name=self.runtime_name)
        runtime_directory = Path(__file__).resolve().parent / self.runtime_name
        shadow_config = ShadowConfigV10_2(
            stop_loss_percent=self.config.stop_loss_percent,
            reward_ratio=self.config.reward_ratio,
            fee_rate=self.config.fee_rate,
            slippage_bps=self.config.slippage_bps,
            entry_delay_ms=self.config.max_entry_delay_ms,
        )
        self.shadow = ShadowOutcomeEngineV10_2(
            runtime_directory / "shadow_outcomes_v10_2.sqlite3",
            shadow_config,
        )
        self.shadow_signals = ShadowSignalsV10_2()
        self.shadow_signals.updated.connect(window.update_shadow)
        self._last_shadow_emit = 0.0
        self._last_position_path_event_time = 0
        self._shadow_closed = False
        self._emit_shadow_stats(force=True)

    def print_startup_banner(self) -> None:
        print("=" * 76)
        print("TradingBot V10.2 - CURRENT BINANCE FEEDS / FORWARD PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Feed: Binance /market + /public split sockets; REST watchdog retained")
        print("V9 entries UNCHANGED; independent 60m shadow outcomes enabled")
        print("Daily-loss gate remains SHADOW ONLY for this paper measurement")
        print("Do not run terminal_v10.py or terminal_v10_1.py at the same time")
        print("=" * 76)

    def _emit_shadow_stats(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_shadow_emit < 0.5:
            return
        self._last_shadow_emit = now
        self.shadow_signals.updated.emit(self.shadow.stats())

    def _diagnostic_snapshot(
        self,
        candle: dict[str, Any],
        signal: str,
    ) -> dict[str, Any]:
        snapshot = super()._diagnostic_snapshot(candle, signal)
        snapshot.update(self.market_data.channel_health_snapshot())
        return snapshot

    async def process_candle(self, candle: dict[str, Any]) -> None:
        await super().process_candle(candle)
        snapshot = dict(self.latest_snapshot)
        signal = str(snapshot.get("signal", "WAIT"))
        if (
            signal in {"LONG", "SHORT"}
            and bool(snapshot.get("entry_time_eligible"))
            and not bool(snapshot.get("data_stale"))
        ):
            candidate_id = self.shadow.add_candidate(candle, signal, snapshot)
            if candidate_id is not None:
                print(
                    "[SHADOW] "
                    f"candidate={candidate_id} side={signal} "
                    f"decision={int(candle['close_time'])}",
                    flush=True,
                )
        self._emit_shadow_stats(force=True)

    async def handle_trade_event(self, trade: dict[str, Any]) -> None:
        # This callback receives every deduplicated trade. Freshness controls
        # entries, but all post-entry trades remain valid path/exit evidence.
        self.order_flow.update(trade)
        self.shadow.on_trade(trade)
        if not bool(trade.get("entry_eligible", False)):
            self._handle_replayed_position_path(trade)
        self._emit_shadow_stats()

    def _handle_replayed_position_path(self, trade_event: dict[str, Any]) -> None:
        position = self.position_manager.get_position()
        if position is None:
            return
        event_time = int(trade_event["event_time"])
        if event_time <= int(position["entry_event_time"]):
            return
        if event_time <= self._last_position_path_event_time:
            return
        self._last_position_path_event_time = event_time
        price = float(trade_event["price"])
        source = str(trade_event.get("source", "RECOVERED_TRADE"))
        self.path_tracker.observe(price, event_time)
        closed = self.position_manager.check_exit(price, event_time, source)
        if closed is not None:
            self._record_closed_trade(closed)
            return
        updated = self.position_manager.update_unrealized_pnl(price)
        if updated is not None:
            self.signals.current_pnl.emit(float(updated["current_pnl"]))

    def _open_at_observed_price(
        self,
        pending,
        market_price: float,
        event_time_ms: int,
        execution_source: str,
    ) -> None:
        super()._open_at_observed_price(
            pending,
            market_price,
            event_time_ms,
            execution_source,
        )
        self._last_position_path_event_time = int(event_time_ms)

    async def stop(self) -> None:
        try:
            await super().stop()
        finally:
            if not self._shadow_closed:
                censored = self.shadow.censor_unfinished("SHUTDOWN")
                if censored:
                    print(
                        f"[SHADOW] censored {censored} unfinished candidate(s) at shutdown"
                    )
                self.shadow.close()
                self._shadow_closed = True


def main() -> int:
    app = QApplication(sys.argv)
    project_directory = Path(__file__).resolve().parent
    lock = QLockFile(str(project_directory / ".xauusdt_v10_2.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.2 already running",
            "Another V10.2 instance already owns this project. Close it before starting a second copy.",
        )
        return 2

    window = TradingWindowV10_2()
    window.show()
    bot = TradingBotV10_2(window)
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
