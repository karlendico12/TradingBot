"""V10.1 observational market-structure and safety extension.

The V9 signal and V10 execution model remain frozen. Structural, candle,
regime, order-flow, and health features are recorded but do not select trades.
Only stale-data and daily-loss safety gates can block a new paper entry.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel

from core.diagnostics_v10_1 import (
    BookQualityTracker,
    CausalStructureTracker,
    DiagnosticStoreV10_1,
    OrderFlowTracker,
    StrategyHealthTracker,
    TradePathTracker,
    candle_pattern,
    market_regime,
    utc_session,
)
from core.execution_v10 import PendingEntry, candle_entry_is_timely
from terminal_v10 import AsyncBotRunner, TradingBotV10, TradingWindowV10


class DiagnosticSignalsV10_1(QObject):
    diagnostics = pyqtSignal(dict)


class TradingWindowV10_1(TradingWindowV10):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.1 - STRUCTURE DIAGNOSTIC PAPER")
        self.title_label.setText("TradingBot V10.1 - STRUCTURE DIAGNOSTIC PAPER")

        self.structure_label = QLabel("Structure: WARMUP")
        self.market_label = QLabel("Market: WARMUP")
        self.flow_label = QLabel("Order Flow: WARMUP")
        self.safety_label = QLabel("Safety: WARMUP")
        chart_index = self.layout.indexOf(self.chart)
        for label in (
            self.structure_label,
            self.market_label,
            self.flow_label,
            self.safety_label,
        ):
            self.layout.insertWidget(chart_index, label)
            chart_index += 1

        # Create chart overlays once and reuse them.
        self.swing_high_item = pg.ScatterPlotItem(
            x=[],
            y=[],
            symbol="t",
            size=13,
            brush=pg.mkBrush("yellow"),
            pen=pg.mkPen("yellow"),
        )
        self.swing_low_item = pg.ScatterPlotItem(
            x=[],
            y=[],
            symbol="t1",
            size=13,
            brush=pg.mkBrush("cyan"),
            pen=pg.mkPen("cyan"),
        )
        self.liquidity_high_line = pg.InfiniteLine(
            pos=0.0,
            angle=0,
            pen=pg.mkPen("yellow", width=1, style=Qt.PenStyle.DotLine),
        )
        self.liquidity_low_line = pg.InfiniteLine(
            pos=0.0,
            angle=0,
            pen=pg.mkPen("cyan", width=1, style=Qt.PenStyle.DotLine),
        )
        self.liquidity_high_line.setVisible(False)
        self.liquidity_low_line.setVisible(False)

        self.chart.addItem(self.swing_high_item)
        self.chart.addItem(self.swing_low_item)
        self.chart.addItem(self.liquidity_high_line, ignoreBounds=True)
        self.chart.addItem(self.liquidity_low_line, ignoreBounds=True)
        self.swing_high_item.setZValue(2)
        self.swing_low_item.setZValue(2)
        self.liquidity_high_line.setZValue(2)
        self.liquidity_low_line.setZValue(2)

    def update_diagnostics(self, snapshot: dict[str, Any]) -> None:
        high = snapshot.get("last_swing_high")
        low = snapshot.get("last_swing_low")
        self.structure_label.setText(
            "Structure: "
            f"High={high:.2f} " if high is not None else "Structure: High=-- "
        )
        self.structure_label.setText(
            self.structure_label.text()
            + (f"Low={low:.2f}" if low is not None else "Low=--")
        )
        self.market_label.setText(
            f"Market: {snapshot.get('session', '--')} | "
            f"{snapshot.get('regime', '--')} | "
            f"Pattern={snapshot.get('candle_pattern', 'NONE')} | "
            f"Health={snapshot.get('strategy_health', '--')}"
        )
        imbalance = float(snapshot.get("flow_imbalance_60s", 0.0) or 0.0)
        spread = snapshot.get("spread_bps")
        spread_text = f"{float(spread):.2f}bps" if spread is not None else "--"
        self.flow_label.setText(
            f"Order Flow: imbalance={imbalance:+.3f} | "
            f"trades60s={int(snapshot.get('trade_count_60s', 0) or 0)} | "
            f"spread={spread_text} | feed={snapshot.get('feed_source', '--')}"
        )
        self.safety_label.setText(
            f"Safety: {snapshot.get('safety_gate', '--')} | "
            f"daily=${float(snapshot.get('daily_net_pnl', 0.0)):+.2f} | "
            f"limit=${float(snapshot.get('daily_loss_limit', 0.0)):.2f}"
        )

    def update_chart(self, candles: list[dict[str, Any]]) -> None:
        super().update_chart(candles)

        bot = getattr(self, "bot", None)
        if bot is None or not candles:
            self.swing_high_item.setData(x=[], y=[])
            self.swing_low_item.setData(x=[], y=[])
            self.liquidity_high_line.setVisible(False)
            self.liquidity_low_line.setVisible(False)
            return

        time_to_index = {
            int(candle["time"]): index
            for index, candle in enumerate(candles)
        }

        highs = [
            item
            for item in bot.structure.highs[-8:]
            if int(item["time"]) in time_to_index
        ]
        lows = [
            item
            for item in bot.structure.lows[-8:]
            if int(item["time"]) in time_to_index
        ]

        if highs:
            self.swing_high_item.setData(
                x=[time_to_index[int(item["time"])] for item in highs],
                y=[float(item["price"]) for item in highs],
            )
            self.liquidity_high_line.setPos(float(highs[-1]["price"]))
            self.liquidity_high_line.setVisible(True)
        else:
            self.swing_high_item.setData(x=[], y=[])
            self.liquidity_high_line.setVisible(False)

        if lows:
            self.swing_low_item.setData(
                x=[time_to_index[int(item["time"])] for item in lows],
                y=[float(item["price"]) for item in lows],
            )
            self.liquidity_low_line.setPos(float(lows[-1]["price"]))
            self.liquidity_low_line.setVisible(True)
        else:
            self.swing_low_item.setData(x=[], y=[])
            self.liquidity_low_line.setVisible(False)



class TradingBotV10_1(TradingBotV10):
    daily_loss_percent = 2.0
    # FORWARD-PAPER TEST MODE ONLY. Keep calculating the 2% daily loss
    # threshold for diagnostics, but do not block new entries with it.
    daily_loss_gate_enabled = False
    hard_trade_staleness_ms = 10_000

    def __init__(
        self,
        window: TradingWindowV10_1,
        runtime_name: str = "runtime_v10_1",
    ) -> None:
        super().__init__(window, runtime_name=runtime_name)
        self.structure = CausalStructureTracker(left=3, right=3)
        self.order_flow = OrderFlowTracker(window_ms=60_000)
        self.book_quality = BookQualityTracker()
        self.path_tracker = TradePathTracker()
        self.health = StrategyHealthTracker(self.store.recent_net_pnls(20))
        self.latest_snapshot: dict[str, Any] = {}

        # The asyncio market-data loop runs in a normal Python worker thread.
        # Any GUI updates must cross into Qt's main thread via a Qt signal.
        self.diagnostic_signals = DiagnosticSignalsV10_1()
        self.diagnostic_signals.diagnostics.connect(
            self.window.update_diagnostics
        )

        diagnostic_path = (
            Path(__file__).resolve().parent
            / runtime_name
            / "diagnostics_v10_1.sqlite3"
        )
        self.diagnostic_store = DiagnosticStoreV10_1(diagnostic_path)
        self._diagnostic_store_closed = False

    def print_startup_banner(self) -> None:
        print("=" * 72)
        print("TradingBot V10.1 - STRUCTURE DIAGNOSTIC / FORWARD PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print(
            "V9 EMA entries frozen; structure/pattern/regime/order-flow/health "
            "are DIAGNOSTIC ONLY"
        )
        if self.daily_loss_gate_enabled:
            print("Safety gates: stale trade data and 2% UTC daily realized loss")
        else:
            print("Safety gates: stale trade data ONLY; DAILY_LOSS DISABLED FOR PAPER TESTING")
        print("=" * 72)

    def market_callbacks(self) -> dict[str, Any]:
        callbacks = super().market_callbacks()
        callbacks["trade_callback"] = self.handle_trade_event
        callbacks["book_callback"] = self.handle_book_event
        return callbacks

    def handle_trade_event(self, trade: dict[str, Any]) -> None:
        self.order_flow.update(trade)

    def handle_book_event(self, book: dict[str, Any]) -> None:
        self.book_quality.update(book)
        super().handle_book_event(book)

    async def process_historical_candle(self, candle: dict[str, Any]) -> None:
        await super().process_historical_candle(candle)
        self.structure.add_candle(candle)

    def _daily_safety(self, decision_time_ms: int) -> dict[str, Any]:
        utc_date = datetime.fromtimestamp(
            decision_time_ms / 1000,
            tz=timezone.utc,
        ).date().isoformat()
        daily_pnl = self.store.daily_net_pnl(utc_date)
        day_start_equity = max(0.01, self.position_manager.equity - daily_pnl)
        limit = day_start_equity * self.daily_loss_percent / 100.0
        would_block = daily_pnl <= -limit
        return {
            "utc_date": utc_date,
            "daily_net_pnl": daily_pnl,
            "daily_loss_limit": limit,
            "daily_loss_gate_enabled": self.daily_loss_gate_enabled,
            "daily_loss_would_block": would_block,
            "daily_loss_blocked": self.daily_loss_gate_enabled and would_block,
        }

    def _diagnostic_snapshot(
        self,
        candle: dict[str, Any],
        signal: str,
    ) -> dict[str, Any]:
        decision_time = int(candle["close_time"])
        candles = self.candle_engine.get_candles()
        snapshot: dict[str, Any] = {
            "signal": signal,
            "session": utc_session(decision_time),
            "candle_pattern": candle_pattern(candles),
            "strategy_health": self.health.state(),
        }
        snapshot.update(market_regime(candles))
        snapshot.update(self.structure.snapshot(candle))
        snapshot.update(self.order_flow.snapshot(decision_time))
        snapshot.update(self.book_quality.snapshot(decision_time))
        snapshot.update(self._daily_safety(decision_time))

        trade_age = snapshot.get("trade_age_ms")
        stale = trade_age is None or int(trade_age) > self.hard_trade_staleness_ms
        gates = []
        if stale:
            gates.append("DATA_STALE")
        if snapshot["daily_loss_blocked"]:
            gates.append("DAILY_LOSS")
        snapshot["data_stale"] = stale
        snapshot["safety_gate"] = "+".join(gates) if gates else "PASS"
        return snapshot

    async def process_candle(self, candle: dict[str, Any]) -> None:
        try:
            self.candle_engine.add_candle(candle)
            self._live_preview_candle = None
            self.structure.add_candle(candle)
            candles = self.candle_engine.get_candles()
            result = self.signal_engine.generate_signal(candles)
            signal = str(result.get("signal", "WAIT"))
            reason = str(result.get("reason", ""))
            snapshot = self._diagnostic_snapshot(candle, signal)
            snapshot["candle_source"] = str(candle.get("source", "UNKNOWN"))
            snapshot["candle_recovered"] = bool(
                candle.get("recovered") or candle.get("replayed")
            )
            snapshot["entry_time_eligible"] = candle_entry_is_timely(
                candle,
                self.config.max_entry_delay_ms,
            )
            self.latest_snapshot = snapshot

            self.signals.signal.emit(signal)
            self.signals.signal_reason.emit(reason)
            self.diagnostic_signals.diagnostics.emit(snapshot)
            self.diagnostic_store.record_decision(
                candle_time=int(candle["time"]),
                decision_time=int(candle["close_time"]),
                signal=signal,
                safety_gate=str(snapshot["safety_gate"]),
                features=snapshot,
            )
            print(
                "[DECISION] "
                f"candle={int(candle['time'])} "
                f"close={int(candle['close_time'])} "
                f"signal={signal} gate={snapshot['safety_gate']} "
                f"source={snapshot['candle_source']} "
                f"recovered={snapshot['candle_recovered']}",
                flush=True,
            )

            if signal not in {"LONG", "SHORT"}:
                self.pending_entry = None
            elif not snapshot["entry_time_eligible"]:
                self.pending_entry = None
                self.signals.status.emit(
                    f"{signal} recorded from recovered stale candle; entry suppressed"
                )
                print(
                    "[INTEGRITY] Decision recorded but stale recovery cannot enter: "
                    f"{signal} candle={int(candle['time'])}"
                )
            elif snapshot["safety_gate"] != "PASS":
                self.pending_entry = None
                self.signals.status.emit(
                    f"{signal} blocked by safety gate: {snapshot['safety_gate']}"
                )
            else:
                current = self.position_manager.get_position()
                if current is not None and current["position"] == signal:
                    self.pending_entry = None
                else:
                    self.pending_entry = PendingEntry(
                        signal=signal,
                        candle_time=int(candle["time"]),
                        decision_time_ms=int(candle["close_time"]),
                    )
                    self.signals.status.emit(
                        f"{signal} queued; diagnostics recorded; awaiting next trade"
                    )
            self._emit_live_chart(force=True)
        except Exception:
            self.signals.status.emit("V10.1 candle diagnostic error")
            traceback.print_exc()

    def _open_at_observed_price(
        self,
        pending: PendingEntry,
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
        position = self.position_manager.get_position()
        if position is None:
            return
        position["metadata"] = {
            "decision_features": dict(self.latest_snapshot),
            "entry_latency_ms": int(event_time_ms) - int(pending.decision_time_ms),
            "v10_1_diagnostics_only": True,
        }
        self.store.save_position(position)
        self.path_tracker.start(position)

    async def handle_price(
        self,
        price: float,
        event_time_ms: int,
        execution_source: str = "UNKNOWN",
    ) -> None:
        self.path_tracker.observe(price, event_time_ms)
        await super().handle_price(price, event_time_ms, execution_source)

    def _record_closed_trade(self, trade: dict[str, Any] | None) -> None:
        if trade is None:
            return
        metadata = dict(trade.get("metadata", {}))
        metadata["path"] = self.path_tracker.finish()
        metadata["health_before_close"] = self.health.state()
        trade["metadata"] = metadata
        super()._record_closed_trade(trade)
        self.health.update(float(trade["net_pnl"]))

    async def stop(self) -> None:
        try:
            await super().stop()
        finally:
            if not self._diagnostic_store_closed:
                self.diagnostic_store.close()
                self._diagnostic_store_closed = True


def main() -> int:
    app = QApplication(sys.argv)

    window = TradingWindowV10_1()
    window.show()

    bot = TradingBotV10_1(window)
    window.bot = bot

    runner = AsyncBotRunner(bot)
    window.bot_runner = runner
    runner.start()

    try:
        return app.exec()
    finally:
        runner.stop()


if __name__ == "__main__":
    raise SystemExit(main())
