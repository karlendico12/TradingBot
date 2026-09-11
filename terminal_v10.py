"""TradingBot V10: cost-aware, streamed, forward-paper execution.

V10 intentionally keeps SignalEngineV9 unchanged.  This version measures that
signal honestly; it does not claim the EMA hypothesis is profitable.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPicture
from PyQt6.QtWidgets import QApplication

from core.candle_engine import CandleEngine
from core.execution_v10 import (
    ExecutionConfig,
    PaperPositionManagerV10,
    PendingEntry,
    candle_entry_is_timely,
)
from core.market_data_v10 import BinanceMarketDataV10
from core.paper_store_v10 import PaperStoreV10
from core.signal_engine_v9 import SignalEngineV9
from terminal_v9 import BotSignals, CandlestickItem, TradingWindow


class TradingWindowV10(TradingWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10 - COST-AWARE FORWARD PAPER")
        self.signal_reason_label.setText(
            "Signal Reason: V9 hypothesis / V10 execution measurement"
        )

        # V9 clears and rebuilds every graphics object on every preview tick.
        # On a long-running Windows session that creates enough QObject/graphics
        # churn to exhaust the process' Window Manager handle allowance. V10
        # keeps one object of each type and only replaces its data.
        self.candle_item = CandlestickItem([])
        self.candle_item.setZValue(0)
        self.chart.addItem(self.candle_item)
        self.ema5_item = self.chart.plot(
            [], [], pen=pg.mkPen("#2962FF", width=2)
        )
        self.ema13_item = self.chart.plot(
            [], [], pen=pg.mkPen("#FFB300", width=2)
        )
        self.ema5_item.setZValue(1)
        self.ema13_item.setZValue(1)

        self.entry_line = pg.InfiniteLine(
            pos=0.0, angle=0, pen=pg.mkPen("cyan", width=2)
        )
        self.stop_line = pg.InfiniteLine(
            pos=0.0,
            angle=0,
            pen=pg.mkPen("red", width=2, style=Qt.PenStyle.DashLine),
        )
        self.tp_line = pg.InfiniteLine(
            pos=0.0,
            angle=0,
            pen=pg.mkPen("green", width=2, style=Qt.PenStyle.DashLine),
        )
        self.entry_marker = pg.ScatterPlotItem(x=[], y=[])
        for item in (
            self.entry_line,
            self.stop_line,
            self.tp_line,
            self.entry_marker,
        ):
            item.setZValue(3)
            item.setVisible(False)
            # Distant stop/target levels must not flatten the candle chart.
            self.chart.addItem(item, ignoreBounds=True)

        self._displayed_position: dict[str, Any] | None = None

    @staticmethod
    def _ema(closes: list[float], period: int) -> list[float]:
        alpha = 2.0 / (period + 1.0)
        value = closes[0]
        values: list[float] = []
        for price in closes:
            value = alpha * price + (1.0 - alpha) * value
            values.append(value)
        return values

    def update_position(self, position: dict[str, Any] | None) -> None:
        super().update_position(position)
        if position is None:
            # V9 returned before removing old overlay objects.
            self.update_trade_overlay(None)

    def update_chart(self, candles: list[dict[str, Any]]) -> None:
        self.last_candles = list(candles)
        if len(self.last_candles) < 2:
            return

        self.candle_item.prepareGeometryChange()
        self.candle_item.candles = self.last_candles
        self.candle_item.picture = QPicture()
        self.candle_item.generatePicture()
        self.candle_item.update()
        self.candle_item.informViewBoundsChanged()

        closes = [float(candle["close"]) for candle in self.last_candles]
        x_values = list(range(len(closes)))
        self.ema5_item.setData(x_values, self._ema(closes, 5))
        self.ema13_item.setData(x_values, self._ema(closes, 13))

        count = len(self.last_candles)
        if not self.chart_user_navigated:
            self.chart.setXRange(max(0, count - 120), count + 2, padding=0)
        self.chart.enableAutoRange(axis="y")

        if self._displayed_position is not None:
            self.update_trade_overlay(self._displayed_position)

    def update_trade_overlay(self, position: dict[str, Any] | None) -> None:
        items = (
            self.entry_line,
            self.stop_line,
            self.tp_line,
            self.entry_marker,
        )
        if position is None:
            self._displayed_position = None
            for item in items:
                item.setVisible(False)
            self.entry_marker.setData(x=[], y=[])
            return

        try:
            displayed = dict(position)
            entry = float(displayed["entry"])
            stop = float(displayed["stop_loss"])
            target = float(displayed["take_profit"])
            side = str(displayed["position"])
        except (KeyError, TypeError, ValueError):
            traceback.print_exc()
            return

        self._displayed_position = displayed
        self.entry_line.setPos(entry)
        self.stop_line.setPos(stop)
        self.tp_line.setPos(target)

        marker_x = max(0, len(self.last_candles) - 1)
        candle_time = displayed.get("candle_time")
        if candle_time is not None:
            marker_x = next(
                (
                    index
                    for index, candle in enumerate(self.last_candles)
                    if int(candle["time"]) == int(candle_time)
                ),
                marker_x,
            )
        color = "green" if side == "LONG" else "red"
        self.entry_marker.setData(
            x=[marker_x],
            y=[entry],
            symbol="t1" if side == "LONG" else "t",
            size=16,
            brush=pg.mkBrush(color),
            pen=pg.mkPen(color),
        )
        for item in items:
            item.setVisible(True)

    def update_closed_trade(self, trade: dict[str, Any] | None) -> None:
        if trade is None:
            return
        try:
            pnl = float(trade.get("net_pnl", trade.get("pnl", 0.0)))
            reason = str(trade.get("reason", "UNKNOWN"))
            side = str(trade.get("position", "UNKNOWN"))
            self.last_trade_label.setText(
                f"Last Trade: {side} | {reason} | Net P/L: ${pnl:.2f}"
            )
            self.current_pnl_label.setText("Current Trade P/L: $0.00")
        except (TypeError, ValueError):
            traceback.print_exc()

    def closeEvent(self, event) -> None:
        """Let the outer runner stop network and database work after Qt exits."""
        self._shutdown_started = True
        event.accept()


class TradingBotV10:
    # Five visual updates per second feels live without rebuilding a 500-candle
    # QPicture for every individual aggregate trade.
    chart_refresh_seconds = 0.20
    shutdown_price_max_age_ms = 5_000

    def __init__(
        self,
        window: TradingWindowV10,
        runtime_name: str = "runtime_v10",
    ) -> None:
        self.window = window
        self.signals = BotSignals()
        self.signals.chart.connect(window.update_chart)
        self.signals.price.connect(window.update_price)
        self.signals.signal.connect(window.update_signal)
        self.signals.signal_reason.connect(window.update_signal_reason)
        self.signals.position.connect(window.update_position)
        self.signals.trade_closed.connect(window.update_closed_trade)
        self.signals.total_pnl.connect(window.update_total_pnl)
        self.signals.status.connect(window.update_status)
        self.signals.stats.connect(window.update_stats)
        self.signals.current_pnl.connect(window.update_current_pnl)

        self.config = ExecutionConfig(
            starting_balance=1_000.0,
            risk_percent=1.0,
            stop_loss_percent=0.002,
            reward_ratio=2.0,
            max_notional_multiple=3.0,
            fee_rate=0.0004,
            slippage_bps=1.0,
            max_entry_delay_ms=5_000,
        )
        self.market_data = BinanceMarketDataV10(symbol="XAUUSDT", interval="3m")
        self.candle_engine = CandleEngine()
        self.signal_engine = SignalEngineV9()

        runtime_directory = Path(__file__).resolve().parent / runtime_name
        self.store = PaperStoreV10(runtime_directory / "paper_v10.sqlite3")
        interrupted = self.store.quarantine_interrupted_position()
        stats = self.store.stats()
        self.position_manager = PaperPositionManagerV10(
            self.config,
            realized_net_pnl=float(stats["total_pnl"]),
        )

        self.total_trades = int(stats["trades"])
        self.wins = int(stats["wins"])
        self.losses = int(stats["losses"])
        self.last_price: float | None = None
        self.last_price_event_time: int | None = None
        self.pending_entry: PendingEntry | None = None
        self.running = False
        self._stopped = False
        self._last_market_gui_emit = 0.0
        self._last_pnl_gui_emit = 0.0
        self._last_chart_gui_emit = 0.0
        self._last_authoritative_display_monotonic = 0.0
        self._live_preview_candle: dict[str, Any] | None = None

        # Stream callbacks and trade lifecycle events drive the GUI. A polling
        # QTimer is unnecessary and consumes an additional Win32 timer handle.
        self.gui_timer = None

        self._emit_stats()
        self.sync_gui()
        if interrupted is not None:
            message = (
                "Previous position quarantined: offline stop/target path is unknown"
            )
            print(f"[INTEGRITY] {message}")
            self.signals.status.emit(message)

    def _emit_stats(self) -> None:
        self.signals.stats.emit(self.total_trades, self.wins, self.losses)
        self.signals.total_pnl.emit(self.position_manager.get_total_pnl())

    def sync_gui(self) -> None:
        position = self.position_manager.get_position()
        self.signals.position.emit(position)
        self.signals.current_pnl.emit(self.position_manager.get_unrealized_pnl())
        self.signals.total_pnl.emit(self.position_manager.get_total_pnl())

    def _emit_live_chart(self, *, force: bool = False) -> bool:
        """Emit a chart-only forming candle without touching decision data."""
        monotonic_now = time.monotonic()
        if (
            not force
            and monotonic_now - self._last_chart_gui_emit
            < self.chart_refresh_seconds
        ):
            return False

        completed = self.candle_engine.get_candles()
        payload = [dict(candle) for candle in completed[-500:]]
        preview = self._live_preview_candle
        if preview is not None:
            preview_time = int(preview["time"])
            if payload and int(payload[-1]["time"]) == preview_time:
                payload[-1] = dict(preview)
            elif not payload or preview_time > int(payload[-1]["time"]):
                payload.append(dict(preview))
                payload = payload[-500:]

        if not payload:
            return False
        self._last_chart_gui_emit = monotonic_now
        self.signals.chart.emit(payload)
        return True

    def _update_live_chart_from_price(
        self,
        price: float,
        event_time_ms: int,
        execution_source: str,
    ) -> None:
        """Update only the visual forming candle from a genuine trade print."""
        interval_ms = int(self.market_data.interval_ms)
        open_time = event_time_ms - (event_time_ms % interval_ms)
        completed = self.candle_engine.get_candles()
        if completed and open_time <= int(completed[-1]["time"]):
            # Historical/replayed prints must never move the chart backwards.
            return

        preview = self._live_preview_candle
        if preview is None or int(preview["time"]) != open_time:
            preview = {
                "time": open_time,
                "close_time": open_time + interval_ms - 1,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
                "closed": False,
                "replayed": False,
                "chart_only": True,
                "chart_source": execution_source,
            }
        else:
            preview = dict(preview)
            preview["high"] = max(float(preview["high"]), price)
            preview["low"] = min(float(preview["low"]), price)
            preview["close"] = price
            preview["chart_source"] = execution_source

        self._live_preview_candle = preview
        self._emit_live_chart()

    def _publish_visual_price(
        self,
        price: float,
        event_time_ms: int,
        source: str,
    ) -> None:
        """Update only the price label and forming chart candle."""
        self._update_live_chart_from_price(price, event_time_ms, source)
        monotonic_now = time.monotonic()
        if monotonic_now - self._last_market_gui_emit >= 0.10:
            self._last_market_gui_emit = monotonic_now
            self.signals.price.emit(price)

    def handle_display_price(
        self,
        price: float,
        event_time_ms: int,
        source: str = "BINANCE_LAST_PRICE",
    ) -> None:
        """Receive Binance's display-only last price; never execute on it."""
        self._last_authoritative_display_monotonic = time.monotonic()
        self._publish_visual_price(float(price), int(event_time_ms), source)

    def handle_book_event(self, book: dict[str, Any]) -> None:
        """Use book midpoint only if the authoritative display poll is stale."""
        if time.monotonic() - self._last_authoritative_display_monotonic <= 2.0:
            return
        try:
            bid = float(book["bid"])
            ask = float(book["ask"])
            event_time_ms = int(book["event_time"])
            if bid <= 0.0 or ask < bid:
                return
        except (KeyError, TypeError, ValueError):
            return
        self._publish_visual_price(
            (bid + ask) / 2.0,
            event_time_ms,
            "BOOK_MID_FALLBACK",
        )

    def _record_closed_trade(self, trade: dict[str, Any] | None) -> None:
        if trade is None:
            return
        # One SQLite transaction records the trade and clears active state.
        self.store.commit_close(trade)
        pnl = float(trade["net_pnl"])
        self.total_trades += 1
        if pnl > 0:
            self.wins += 1
        else:
            self.losses += 1

        print(
            "[PAPER CLOSE] "
            f"{trade['position']} {trade['reason']} | "
            f"gross=${trade['gross_pnl']:.2f} "
            f"fees=${trade['fees']:.2f} "
            f"funding=${trade['funding_pnl']:.4f} "
            f"net=${trade['net_pnl']:.2f} "
            f"equity=${trade['balance_after']:.2f}"
        )
        self.signals.trade_closed.emit(trade)
        self.signals.position.emit(None)
        self.signals.current_pnl.emit(0.0)
        self._emit_stats()

    def _open_at_observed_price(
        self,
        pending: PendingEntry,
        market_price: float,
        event_time_ms: int,
        execution_source: str,
    ) -> None:
        position = self.position_manager.open_position(
            pending.signal,
            market_price,
            pending.candle_time,
            event_time_ms,
            execution_source,
        )
        self.store.save_position(position)
        capped = float(position["notional"]) + 1e-9 >= (
            self.position_manager.equity * self.config.max_notional_multiple
        )
        print(
            "[PAPER OPEN] "
            f"{pending.signal} observed={market_price:.2f} "
            f"fill={position['entry']:.2f} qty={position['quantity']:.5f} "
            f"notional=${position['notional']:.2f} "
            f"planned_stop=${position['planned_stop_loss']:.2f} "
            f"notional_cap={'YES' if capped else 'NO'}"
        )
        self.signals.position.emit(position)
        self.signals.current_pnl.emit(float(position["current_pnl"]))

    async def handle_price(
        self,
        price: float,
        event_time_ms: int,
        execution_source: str = "UNKNOWN",
    ) -> None:
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
            self._publish_visual_price(
                price,
                event_time_ms,
                execution_source,
            )
            monotonic_now = time.monotonic()
            refresh_gui = monotonic_now - self._last_pnl_gui_emit >= 0.10
            if refresh_gui:
                self._last_pnl_gui_emit = monotonic_now

            trade = self.position_manager.check_exit(
                price,
                event_time_ms,
                execution_source,
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
                self.signals.status.emit("Signal cancelled: no timely next trade print")
                print("[ENTRY] Cancelled stale pending signal")
                return

            current = self.position_manager.get_position()
            if current is not None:
                if current["position"] == pending.signal:
                    return
                reversal = self.position_manager.close_position(
                    price,
                    "REVERSAL",
                    event_time_ms,
                    execution_source,
                )
                self._record_closed_trade(reversal)

            self._open_at_observed_price(
                pending,
                price,
                event_time_ms,
                execution_source,
            )
        except Exception:
            self.running = False
            self.signals.status.emit("FATAL paper-execution error; inspect terminal")
            traceback.print_exc()

    async def handle_funding(
        self,
        funding_time_ms: int,
        funding_rate: float,
        mark_price: float,
    ) -> None:
        payment = self.position_manager.apply_funding(
            funding_time_ms,
            funding_rate,
            mark_price,
        )
        if payment and self.position_manager.get_position() is not None:
            self.store.save_position(self.position_manager.get_position())
            print(
                f"[FUNDING] rate={funding_rate:+.8f} "
                f"paper P/L impact=${payment:+.4f}"
            )

    async def process_historical_candle(self, candle: dict[str, Any]) -> None:
        self.candle_engine.add_candle(candle)

    def handle_history_complete(self) -> None:
        self._live_preview_candle = None
        self._emit_live_chart(force=True)
        self.signals.status.emit("History ready; waiting for streamed market events")

    def handle_preview_candle(self, candle: dict[str, Any]) -> None:
        completed = self.candle_engine.get_candles()
        if completed and int(candle["time"]) <= int(completed[-1]["time"]):
            return
        # The exchange kline is the authoritative forming OHLC snapshot. It is
        # still chart-only and is never inserted into CandleEngine.
        self._live_preview_candle = dict(candle)
        self._emit_live_chart()

    async def process_candle(self, candle: dict[str, Any]) -> None:
        try:
            self.candle_engine.add_candle(candle)
            self._live_preview_candle = None
            candles = self.candle_engine.get_candles()
            result = self.signal_engine.generate_signal(candles)
            signal = str(result.get("signal", "WAIT"))
            reason = str(result.get("reason", ""))
            self.signals.signal.emit(signal)
            self.signals.signal_reason.emit(reason)

            if signal not in {"LONG", "SHORT"}:
                self.pending_entry = None
            elif not candle_entry_is_timely(
                candle,
                self.config.max_entry_delay_ms,
            ):
                self.pending_entry = None
                self.signals.status.emit(
                    f"{signal} observed on recovered stale candle; entry suppressed"
                )
                print(
                    "[INTEGRITY] Suppressed stale recovered decision "
                    f"{signal} candle={int(candle['time'])}"
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
                        f"{signal} decision queued; waiting for next aggregate trade"
                    )
            self._emit_live_chart(force=True)
        except Exception:
            self.signals.status.emit("Candle processing error; inspect terminal")
            traceback.print_exc()

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stopped = False
        self.print_startup_banner()
        try:
            await self.market_data.start(**self.market_callbacks())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.running = False
            self.signals.status.emit(f"Market-data failure: {type(exc).__name__}")
            traceback.print_exc()

    def print_startup_banner(self) -> None:
        print("=" * 64)
        print("TradingBot V10 - FORWARD PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("V9 EMA signal frozen; support/resistance, patterns, and ML are OFF")
        print("=" * 64)

    def market_callbacks(self) -> dict[str, Any]:
        return {
            "candle_callback": self.process_candle,
            "price_callback": self.handle_price,
            "history_callback": self.process_historical_candle,
            "history_complete_callback": self.handle_history_complete,
            "preview_callback": self.handle_preview_candle,
            "funding_callback": self.handle_funding,
            "display_price_callback": self.handle_display_price,
            "book_callback": self.handle_book_event,
            "status_callback": self.signals.status.emit,
        }

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.running = False
        self.pending_entry = None
        try:
            await self.market_data.stop()
        finally:
            position = self.position_manager.get_position()
            now_ms = int(time.time() * 1000)
            shutdown_price_age_ms = (
                None
                if self.last_price_event_time is None
                else now_ms - int(self.last_price_event_time)
            )
            shutdown_price_fresh = (
                shutdown_price_age_ms is not None
                and -1_000
                <= shutdown_price_age_ms
                <= self.shutdown_price_max_age_ms
            )
            if (
                position is not None
                and self.last_price is not None
                and shutdown_price_fresh
            ):
                trade = self.position_manager.close_position(
                    self.last_price,
                    "SHUTDOWN",
                    now_ms,
                    f"SHUTDOWN_RECENT_PRINT_AGE_{shutdown_price_age_ms}MS",
                )
                self._record_closed_trade(trade)
            elif position is not None:
                print(
                    "[INTEGRITY] No sufficiently fresh shutdown trade price; "
                    f"age_ms={shutdown_price_age_ms}. Active state remains for "
                    "quarantine on next launch"
                )
            self.store.close()


class AsyncBotRunner:
    """Run asyncio/network work off the Qt GUI thread without qasync timers."""

    def __init__(self, bot: TradingBotV10) -> None:
        self.bot = bot
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.bot_task: asyncio.Task | None = None
        self.ready = threading.Event()

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.bot_task = loop.create_task(self.bot.start())

        def report_failure(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            exception = task.exception()
            if exception is not None:
                traceback.print_exception(
                    type(exception),
                    exception,
                    exception.__traceback__,
                )

        self.bot_task.add_done_callback(report_failure)
        self.ready.set()
        try:
            loop.run_forever()
        finally:
            pending = [
                task for task in asyncio.all_tasks(loop) if not task.done()
            ]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._thread_main,
            name=f"{type(self.bot).__name__}-AsyncIO",
            daemon=True,
        )
        self.thread.start()
        if not self.ready.wait(timeout=10.0):
            raise RuntimeError("Async bot worker did not start")

    def stop(self, timeout: float = 15.0) -> None:
        loop = self.loop
        thread = self.thread
        if loop is None or thread is None:
            return

        if loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self.bot.stop(), loop)
                future.result(timeout=timeout)
            except Exception:
                traceback.print_exc()

            def finish_loop() -> None:
                if self.bot_task is not None and not self.bot_task.done():
                    self.bot_task.cancel()
                loop.stop()

            try:
                loop.call_soon_threadsafe(finish_loop)
            except RuntimeError:
                pass

        thread.join(timeout=timeout)
        if thread.is_alive():
            print("[SHUTDOWN] Async worker did not stop before timeout")


def main() -> int:
    app = QApplication(sys.argv)
    window = TradingWindowV10()
    window.show()
    bot = TradingBotV10(window)
    window.bot = bot
    runner = AsyncBotRunner(bot)
    window.bot_runner = runner
    try:
        runner.start()
        return app.exec()
    finally:
        runner.stop()


if __name__ == "__main__":
    raise SystemExit(main())
