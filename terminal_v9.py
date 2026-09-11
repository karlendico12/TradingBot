# V8 Fixed 2R - zoom/pan + graceful shutdown + separate persistence
import sys
import asyncio
import traceback
import csv
import json
import os
import pyqtgraph as pg
from pathlib import Path
from datetime import datetime, timezone
from PyQt6.QtGui import QPen
from PyQt6.QtCore import Qt

import pyqtgraph as pg
from PyQt6.QtGui import QPicture, QPainter, QColor
from PyQt6.QtCore import QRectF, QPointF

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
)

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from qasync import QEventLoop

from core.websocket_manager import WebSocketManager
from core.candle_engine import CandleEngine
from core.signal_engine_v9 import SignalEngineV9
from core.risk_manager import RiskManager
from core.position_manager import PositionManager


# ==========================================================
# GUI SIGNALS
# ==========================================================

class BotSignals(QObject):

    price = pyqtSignal(float)
    candle = pyqtSignal(dict)
    signal = pyqtSignal(str)
    signal_reason = pyqtSignal(str)
    position = pyqtSignal(object)
    trade_closed = pyqtSignal(dict)
    total_pnl = pyqtSignal(float)
    current_pnl = pyqtSignal(float)
    status = pyqtSignal(str)
    stats = pyqtSignal(int, int, int)
    chart = pyqtSignal(object)

# ==========================================================
# MAIN WINDOW
# ==========================================================
class CandlestickItem(pg.GraphicsObject):

    def __init__(self, candles):
        super().__init__()
        self.candles = candles
        self.picture = QPicture()
        self.generatePicture()

    def generatePicture(self):

        painter = QPainter(self.picture)

        body_width = 0.12

        for i, c in enumerate(self.candles):

            o = float(c["open"])
            h = float(c["high"])
            l = float(c["low"])
            cl = float(c["close"])

            bullish = cl >= o

            color = QColor("#00C853") if bullish else QColor("#FF3D3D")

            pen = QPen(color)
            pen.setWidthF(0.2)
            painter.setPen(pen)

            painter.drawLine(QPointF(i, l), QPointF(i, h))

            top = max(o, cl)
            bottom = min(o, cl)
            height = max(top - bottom, 0.03)

            painter.setBrush(color)
            painter.setPen(color)

            painter.drawRect(
                QRectF(
                    i - body_width,
                    bottom,
                    body_width * 2,
                    height
                )
            )

        painter.end()

    def paint(self, painter, *args):
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QRectF(self.picture.boundingRect())


class TradingWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle("TradingBot V9 - FILTERED FIXED 2R")
        self.resize(650, 600)

        self.central = QWidget()
        self.setCentralWidget(self.central)

        self.layout = QVBoxLayout()
        self.central.setLayout(self.layout)

        # ==================================================
        # TITLE
        # ==================================================

        self.title_label = QLabel("TradingBot V9 - FILTERED FIXED 2R")
        self.layout.addWidget(self.title_label)

        # ==================================================
        # STATUS
        # ==================================================

        self.status_label = QLabel("Status: Starting...")
        self.layout.addWidget(self.status_label)

        # ==================================================
        # PRICE
        # ==================================================

        self.price_label = QLabel("Price: --")
        self.layout.addWidget(self.price_label)

        # ==================================================
        # SIGNAL
        # ==================================================

        self.signal_label = QLabel("Signal: WAIT")
        self.layout.addWidget(self.signal_label)

        self.signal_reason_label = QLabel("Signal Reason: Waiting for first closed candle")
        self.layout.addWidget(self.signal_reason_label)

        # ==================================================
        # POSITION
        # ==================================================

        self.position_label = QLabel("Position: NONE")
        self.layout.addWidget(self.position_label)

        # ==================================================
        # ENTRY
        # ==================================================

        self.entry_label = QLabel("Entry: --")
        self.layout.addWidget(self.entry_label)

        # ==================================================
        # STOP LOSS
        # ==================================================

        self.stop_label = QLabel("Stop Loss: --")
        self.layout.addWidget(self.stop_label)

        # ==================================================
        # TAKE PROFIT
        # ==================================================

        self.tp_label = QLabel("Take Profit: --")
        self.layout.addWidget(self.tp_label)

        # ==================================================
        # QUANTITY
        # ==================================================

        self.quantity_label = QLabel("Quantity: --")
        self.layout.addWidget(self.quantity_label)

        # ==================================================
        # CURRENT TRADE P/L
        # ==================================================

        self.current_pnl_label = QLabel(
            "Current Trade P/L: $0.00"
        )
        self.layout.addWidget(self.current_pnl_label)

        # ==================================================
        # TOTAL P/L
        # ==================================================

        self.total_pnl_label = QLabel(
            "Total P/L: $0.00"
        )
        self.layout.addWidget(self.total_pnl_label)

        # ==================================================
        # STATISTICS
        # ==================================================

        self.stats_title = QLabel("Statistics")
        self.layout.addWidget(self.stats_title)

        self.trades_label = QLabel("Trades: 0")
        self.layout.addWidget(self.trades_label)

        self.wins_label = QLabel("Wins: 0")
        self.layout.addWidget(self.wins_label)

        self.losses_label = QLabel("Losses: 0")
        self.layout.addWidget(self.losses_label)

        self.winrate_label = QLabel("Win Rate: 0.0%")
        self.layout.addWidget(self.winrate_label)

        # ==================================================
        # LAST TRADE
        # ==================================================

        self.last_trade_label = QLabel(
            "Last Trade: None"
        )
        self.layout.addWidget(self.last_trade_label)

        # ==================================================
        # CHART
        # ==================================================

        self.chart = pg.PlotWidget()

        self.chart.setBackground("#0F1117")
        self.chart.setMinimumHeight(340)

        self.chart.showGrid(x=True, y=True, alpha=0.15)

        self.chart.setMenuEnabled(False)

        # Interactive chart navigation:
        # - Left-drag: pan horizontally
        # - Mouse wheel: zoom
        # The user's manual view is preserved when new candles arrive.
        self.chart.setMouseEnabled(x=True, y=False)
        self.chart_view = self.chart.getViewBox()
        self.chart_view.setMouseMode(pg.ViewBox.PanMode)
        self.chart_user_navigated = False
        self.chart_view.sigRangeChangedManually.connect(
            self._on_chart_range_changed_manually
        )

        self.chart.getAxis("bottom").setStyle(showValues=False)
        self.chart.getAxis("left").setTextPen("#AAAAAA")
        self.chart.getAxis("bottom").setPen("#444444")
        self.chart.getAxis("left").setPen("#444444")

        self.layout.addWidget(self.chart)

        # Chart overlay items
        self.entry_line = None
        self.stop_line = None
        self.tp_line = None
        self.entry_marker = None
        self.last_candles = []

    def update_chart(self, candles):

        self.last_candles = candles

        if len(candles) < 2:
            return

        self.chart.clear()

        self.chart.addItem(CandlestickItem(candles))

        closes = [float(c["close"]) for c in candles]
        x = list(range(len(closes)))

        def ema(period):

            alpha = 2 / (period + 1)

            e = closes[0]

            values = []

            for p in closes:
                e = alpha * p + (1 - alpha) * e
                values.append(e)

            return values

        self.chart.plot(
            x,
            ema(5),
            pen=pg.mkPen("#2962FF", width=2)
        )

        self.chart.plot(
            x,
            ema(13),
            pen=pg.mkPen("#FFB300", width=2)
        )

        count = len(candles)

        # On first load, show about 120 candles like TradingView.
        # After the user drags/zooms, preserve that manual view instead of
        # snapping back whenever a new candle arrives.
        if not self.chart_user_navigated:
            self.chart.setXRange(
                max(0, count - 120),
                count + 2,
                padding=0
            )

        self.chart.enableAutoRange(axis="y")

    def _on_chart_range_changed_manually(self, *args):
        """Remember that the user manually panned or zoomed the chart."""
        self.chart_user_navigated = True

    def update_stats(self, trades, wins, losses):

        self.trades_label.setText(f"Trades: {trades}")
        self.wins_label.setText(f"Wins: {wins}")
        self.losses_label.setText(f"Losses: {losses}")

        rate = (wins / trades * 100) if trades else 0.0

        self.winrate_label.setText(
            f"Win Rate: {rate:.1f}%"
        )

    # ==========================================================
    # UPDATE STATUS
    # ==========================================================

    def update_status(self, message):

        self.status_label.setText(
            f"Status: {message}"
        )

    # ==========================================================
    # UPDATE PRICE
    # ==========================================================

    def update_price(self, price):

        try:
            price = float(price)

            self.price_label.setText(
                f"Price: {price:.2f}"
            )

        except Exception:
            traceback.print_exc()

    # ==========================================================
    # UPDATE SIGNAL
    # ==========================================================

    def update_signal(self, signal):

        self.signal_label.setText(
            f"Signal: {signal}"
        )

    def update_signal_reason(self, reason):

        self.signal_reason_label.setText(
            f"Signal Reason: {reason}"
        )

    # ==========================================================
    # UPDATE POSITION
    # ==========================================================

    def update_position(self, position):

        if position is None:

            self.position_label.setText(
                "Position: NONE"
            )

            self.entry_label.setText(
                "Entry: --"
            )

            self.stop_label.setText(
                "Stop Loss: --"
            )

            self.tp_label.setText(
                "Take Profit: --"
            )

            self.quantity_label.setText(
                "Quantity: --"
            )

            self.current_pnl_label.setText(
                "Current Trade P/L: $0.00"
            )

            return

        try:

            side = position["position"]

            entry = float(
                position["entry"]
            )

            stop_loss = float(
                position["stop_loss"]
            )

            take_profit = float(
                position["take_profit"]
            )

            quantity = float(
                position["quantity"]
            )

            self.position_label.setText(
                f"Position: {side}"
            )

            self.entry_label.setText(
                f"Entry: {entry:.2f}"
            )

            self.stop_label.setText(
                f"Stop Loss: {stop_loss:.2f}"
            )

            self.tp_label.setText(
                f"Take Profit: {take_profit:.2f}"
            )

            self.quantity_label.setText(
                f"Quantity: {quantity:.4f}"
            )

        except Exception:

            traceback.print_exc()

        self.update_trade_overlay(position)

    # ==========================================================
    # UPDATE CURRENT P/L
    # ==========================================================

    def update_current_pnl(self, pnl):

        try:

            pnl = float(pnl)

            self.current_pnl_label.setText(
                f"Current Trade P/L: ${pnl:.2f}"
            )

        except Exception:

            traceback.print_exc()

    # ==========================================================
    # UPDATE TOTAL P/L
    # ==========================================================

    def update_total_pnl(self, pnl):

        try:

            pnl = float(pnl)

            self.total_pnl_label.setText(
                f"Total P/L: ${pnl:.2f}"
            )

        except Exception:

            traceback.print_exc()

    # ==========================================================
    # UPDATE CLOSED TRADE
    # ==========================================================

    def update_closed_trade(self, trade):

        if trade is None:
            return

        try:

            pnl = float(
                trade["pnl"]
            )

            reason = trade["reason"]

            side = trade["position"]

            self.last_trade_label.setText(
                f"Last Trade: {side} | "
                f"{reason} | "
                f"P/L: ${pnl:.2f}"
            )

            self.current_pnl_label.setText(
                "Current Trade P/L: $0.00"
            )

        except Exception:

            traceback.print_exc()

# ==========================================================
# UPDATE TRADE OVERLAY
# ==========================================================

    def update_trade_overlay(self, position):

        # Remove old overlay items
        for name in ("entry_line", "stop_line", "tp_line", "entry_marker"):
            item = getattr(self, name, None)
            if item is not None:
                try:
                    self.chart.removeItem(item)
                except Exception:
                    pass
                setattr(self, name, None)

        if position is None:
            return

        if not hasattr(self, "last_candles") or not self.last_candles:
            return

        entry = float(position["entry"])
        stop = float(position["stop_loss"])
        tp = float(position["take_profit"])
        side = position["position"]

        self.entry_line = pg.InfiniteLine(
            pos=entry,
            angle=0,
            pen=pg.mkPen("cyan", width=2),
        )

        self.stop_line = pg.InfiniteLine(
            pos=stop,
            angle=0,
            pen=pg.mkPen("red", width=2, style=Qt.PenStyle.DashLine),
        )

        self.tp_line = pg.InfiniteLine(
            pos=tp,
            angle=0,
            pen=pg.mkPen("green", width=2, style=Qt.PenStyle.DashLine),
        )

        self.chart.addItem(self.entry_line)
        self.chart.addItem(self.stop_line)
        self.chart.addItem(self.tp_line)

        # Keep all trade levels visible
        low = min(entry, stop, tp)
        high = max(entry, stop, tp)

        self.chart.setYRange(
            low - 2,
            high + 2,
            padding=0
        )

        x = len(self.last_candles) - 1

        self.entry_marker = pg.ScatterPlotItem(
            x=[x],
            y=[entry],
            symbol="t1" if side == "LONG" else "t",
            size=16,
            brush="green" if side == "LONG" else "red",
        )

        self.chart.addItem(self.entry_marker)
    # ======================================================
    # GRACEFUL WINDOW SHUTDOWN
    # ======================================================

    def closeEvent(self, event):
        """
        Do not let Qt destroy the event loop while asyncio/REST tasks
        are still cleaning up. Hide the window first, finish shutdown,
        then quit QApplication.
        """
        if getattr(self, "_shutdown_started", False):
            event.accept()
            return

        self._shutdown_started = True
        event.ignore()
        self.hide()

        try:
            asyncio.create_task(self._shutdown_before_quit())
        except RuntimeError:
            # Fallback only if no asyncio loop is available.
            event.accept()

    async def _shutdown_before_quit(self):
        bot = getattr(self, "bot", None)
        bot_task = getattr(self, "bot_task", None)

        try:
            if bot is not None and hasattr(bot, "stop"):
                try:
                    await asyncio.wait_for(bot.stop(), timeout=8.0)
                except asyncio.TimeoutError:
                    print("[SHUTDOWN] bot.stop() timed out; forcing cancellation")
                except Exception as exc:
                    print(f"[SHUTDOWN] bot.stop() error: {exc}")

            if bot_task is not None and not bot_task.done():
                bot_task.cancel()
                try:
                    await asyncio.wait_for(bot_task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception as exc:
                    print(f"[SHUTDOWN] bot task error: {exc}")

        finally:
            app = QApplication.instance()
            if app is not None:
                app.quit()



# ==========================================================
# TRADING BOT
# ==========================================================

class TradingBot:

    def __init__(self, window):

        self.window = window

        self.signals = BotSignals()

        self.signals.chart.connect(
            self.window.update_chart
        )

        # ==================================================
        # COMPONENTS
        # ==================================================

        self.websocket_manager = WebSocketManager(
            symbol="XAUUSDT",
            interval="3m",
        )

        if hasattr(self.websocket_manager, "set_status_callback"):
            self.websocket_manager.set_status_callback(
                self.signals.status.emit
            )

        self.candle_engine = CandleEngine()

        self.signal_engine = SignalEngineV9()

        self.risk_manager = RiskManager()

        self.position_manager = PositionManager()

        # ==================================================
        # CONNECT SIGNALS
        # ==================================================

        self.signals.price.connect(
            self.window.update_price
        )

        self.signals.signal.connect(
            self.window.update_signal
        )

        self.signals.signal_reason.connect(
            self.window.update_signal_reason
        )

        self.signals.position.connect(
            self.window.update_position
        )

        self.signals.trade_closed.connect(
            self.window.update_closed_trade
        )

        self.signals.total_pnl.connect(
            self.window.update_total_pnl
        )

        self.signals.status.connect(
            self.window.update_status
        )

        self.signals.stats.connect(
            self.window.update_stats
        )

        self.signals.current_pnl.connect(
            self.window.update_current_pnl
        )

        # ==================================================
        # LAST PRICE
        # ==================================================

        self.last_price = None

        # ==================================================
        # BOT RUNNING STATE
        # ==================================================

        self.running = False

        # ==================================================
        # PERFORMANCE COUNTERS
        # ==================================================

        self.total_trades = 0
        self.wins = 0
        self.losses = 0

        # ==================================================
        # TRADE LOG
        # ==================================================
        self.trade_log_file = Path("trades_v9.csv")
        if not self.trade_log_file.exists():
            with open(self.trade_log_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Time","Side","Entry","Exit","Reason","Quantity","PnL"
                ])

        self.load_trade_stats()

        self.active_position_file = Path("active_position_v9.json")
        self.restore_active_position()


        # ==================================================
        # GUI SYNC TIMER
        # ==================================================

        self.gui_timer = QTimer()

        self.gui_timer.timeout.connect(
            self.sync_gui
        )

        self.gui_timer.start(500)

    # ==========================================================
    # ACTIVE POSITION PERSISTENCE
    # ==========================================================

    def save_active_position(self):
        """Persist the current paper position immediately and atomically."""
        try:
            position = self.position_manager.get_position()

            if position is None:
                if self.active_position_file.exists():
                    self.active_position_file.unlink()
                    print(
                        f"[PERSIST] Cleared {self.active_position_file}"
                    )
                return

            temp_file = self.active_position_file.with_suffix(
                self.active_position_file.suffix + ".tmp"
            )

            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(position, f, indent=2)

            os.replace(temp_file, self.active_position_file)

            print(
                f"[PERSIST] Active position saved -> "
                f"{self.active_position_file}"
            )

        except Exception:
            traceback.print_exc()

    def restore_active_position(self):
        """Restore the exact open paper position after a restart."""
        try:
            if not self.active_position_file.exists():
                print("[PERSIST] No active paper position to restore")
                return False

            with open(
                self.active_position_file,
                "r",
                encoding="utf-8"
            ) as f:
                position = json.load(f)

            required = {
                "position",
                "entry",
                "stop_loss",
                "take_profit",
                "quantity",
            }

            missing = required.difference(position.keys())

            if missing:
                raise ValueError(
                    f"Missing active-position fields: "
                    f"{sorted(missing)}"
                )

            # Normalize numeric fields.
            for key in (
                "entry",
                "stop_loss",
                "take_profit",
                "quantity",
            ):
                position[key] = float(position[key])

            if "current_price" in position:
                position["current_price"] = float(
                    position["current_price"]
                )

            if "current_pnl" in position:
                position["current_pnl"] = float(
                    position["current_pnl"]
                )

            if "pnl_percent" in position:
                position["pnl_percent"] = float(
                    position["pnl_percent"]
                )

            # PositionManager stores the live paper position here.
            self.position_manager.position = position

            # Preserve same-candle duplicate-entry protection.
            self.position_manager.last_entry_candle = position.get(
                "candle_time"
            )

            print()
            print("******** RESTORED PAPER POSITION ********")
            print(
                f"Side:        {position['position']}"
            )
            print(
                f"Entry:       {position['entry']:.2f}"
            )
            print(
                f"Stop Loss:   {position['stop_loss']:.2f}"
            )
            print(
                f"Take Profit: {position['take_profit']:.2f}"
            )
            print(
                f"Quantity:    {position['quantity']:.4f}"
            )

            if "tp_method" in position:
                print(
                    f"TP Method:   {position['tp_method']}"
                )

            if "risk_reward" in position:
                print(
                    f"Risk/Reward: 1:"
                    f"{float(position['risk_reward']):.2f}"
                )

            print("*****************************************")
            print()

            # Update GUI immediately.
            self.signals.position.emit(position)

            if "current_pnl" in position:
                self.signals.current_pnl.emit(
                    float(position.get("current_pnl", 0.0))
                )

            return True

        except Exception:
            print(
                "[PERSIST] Failed to restore active position"
            )
            traceback.print_exc()
            return False

    # ==========================================================
    # CALCULATE CURRENT POSITION P/L
    # ==========================================================

    def calculate_current_pnl(self):

        try:

            position = (
                self.position_manager.get_position()
            )

            if position is None:
                return 0.0

            if self.last_price is None:
                return 0.0

            side = position["position"]

            entry = float(
                position["entry"]
            )

            quantity = float(
                position["quantity"]
            )

            current_price = float(
                self.last_price
            )

            if side == "LONG":

                pnl = (
                    current_price - entry
                ) * quantity

            elif side == "SHORT":

                pnl = (
                    entry - current_price
                ) * quantity

            else:

                pnl = 0.0

            return float(pnl)

        except Exception:

            traceback.print_exc()

            return 0.0

    # ==========================================================
    # SYNC GUI
    # ==========================================================

    def sync_gui(self):

        try:

            position = (
                self.position_manager.get_position()
            )

            total_pnl = (
                self.position_manager.get_total_pnl()
            )

            current_pnl = (
                self.calculate_current_pnl()
            )

            self.signals.position.emit(
                position
            )

            self.signals.total_pnl.emit(
                total_pnl
            )

            self.signals.current_pnl.emit(
                current_pnl
            )

        except Exception:

            traceback.print_exc()

    # ==========================================================
    # HANDLE CLOSED TRADE
    # ==========================================================

    def handle_closed_trade(self, trade):

        if trade is None:
            return

        try:

            # Record the actual close/log time. Entry candle_time remains in
            # the trade dict for diagnostics, while Time in CSV is close time.
            trade["time"] = datetime.now(
                timezone.utc
            ).isoformat(timespec="seconds")

            # PositionManager has already cleared the in-memory position.
            # Mirror that state on disk immediately.
            self.save_active_position()

            pnl = float(
                trade["pnl"]
            )

            total_pnl = (
                self.position_manager.get_total_pnl()
            )

            print()

            print(
                "******** PAPER TRADE CLOSED ********"
            )

            print(
                f"Side:        "
                f"{trade['position']}"
            )

            print(
                f"Entry:       "
                f"{trade['entry']:.2f}"
            )

            print(
                f"Exit:        "
                f"{trade['exit']:.2f}"
            )

            print(
                f"Reason:      "
                f"{trade['reason']}"
            )

            print(
                f"Quantity:    "
                f"{trade['quantity']:.4f}"
            )

            print(
                f"Trade P/L:   "
                f"${pnl:.2f}"
            )

            print(
                f"Total P/L:   "
                f"${total_pnl:.2f}"
            )

            print(
                "************************************"
            )

            self.log_trade(trade)

            self.total_trades += 1

            if pnl >= 0:
                self.wins += 1
            else:
                self.losses += 1

            self.signals.stats.emit(
                self.total_trades,
                self.wins,
                self.losses
            )

            self.signals.trade_closed.emit(
                trade
            )

            self.signals.total_pnl.emit(
                total_pnl
            )

            self.signals.current_pnl.emit(
                0.0
            )

            self.signals.position.emit(
                self.position_manager.get_position()
            )

        except Exception:

            traceback.print_exc()


    # ==========================================================
    # SAVE TRADE TO CSV
    # ==========================================================

    def format_trade_time(self, trade):
        """Return a readable UTC timestamp for a closed trade."""
        try:
            value = trade.get("time")
            if value:
                return str(value)

            value = trade.get("candle_time")
            if value is None:
                return datetime.now(timezone.utc).isoformat(timespec="seconds")

            value = float(value)
            if value > 10_000_000_000:
                value /= 1000.0

            return datetime.fromtimestamp(
                value,
                tz=timezone.utc,
            ).isoformat(timespec="seconds")
        except Exception:
            return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def log_trade(self, trade):

        try:

            with open(self.trade_log_file, "a", newline="") as f:

                writer = csv.writer(f)

                writer.writerow([
                    self.format_trade_time(trade),
                    trade.get("position", ""),
                    f'{float(trade.get("entry",0)):.2f}',
                    f'{float(trade.get("exit",0)):.2f}',
                    trade.get("reason", ""),
                    f'{float(trade.get("quantity",0)):.4f}',
                    f'{float(trade.get("pnl",0)):.2f}',
                ])

        except Exception:

            traceback.print_exc()

    def load_trade_stats(self):

        try:
            self.total_trades = 0
            self.wins = 0
            self.losses = 0
            restored_total_pnl = 0.0

            with open(self.trade_log_file, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row:
                        continue

                    try:
                        pnl = float(row.get("PnL", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        continue

                    self.total_trades += 1
                    restored_total_pnl += pnl

                    if pnl >= 0:
                        self.wins += 1
                    else:
                        self.losses += 1

            self.position_manager.total_pnl = float(restored_total_pnl)

            self.signals.stats.emit(
                self.total_trades,
                self.wins,
                self.losses
            )
            self.signals.total_pnl.emit(
                float(restored_total_pnl)
            )

            print(
                f"[STATS] Restored {self.total_trades} trades, "
                f"Total P/L ${restored_total_pnl:.2f}"
            )

        except FileNotFoundError:
            pass
        except Exception:
            traceback.print_exc()

    # ==========================================================
    # CHECK POSITION EXIT
    # ==========================================================

    def check_position_exit(self, current_price):

        try:

            position = (
                self.position_manager.get_position()
            )

            if position is None:
                return None

            trade = (
                self.position_manager.check_exit(
                    current_price
                )
            )

            if trade is not None:

                self.handle_closed_trade(
                    trade
                )

                return trade

        except Exception:

            traceback.print_exc()

        return None

    # ==========================================================
    # PROCESS SIGNAL
    # ==========================================================

    async def process_signal(
        self,
        signal,
        entry_price,
        candle_time,
    ):

        try:

            self.signals.signal.emit(
                signal
            )

            # ==================================================
            # WAIT
            # ==================================================

            if signal not in (
                "LONG",
                "SHORT",
            ):

                print(
                    "No trade signal."
                )

                return

            # ==================================================
            # CHECK ENTRY
            # ==================================================

            allowed, reason = (
                self.position_manager.can_enter(
                    signal,
                    candle_time,
                )
            )

            print(
                f"[POSITION] {reason}"
            )

            if not allowed:
                return

            # ==================================================
            # REVERSAL
            # ==================================================

            if self.position_manager.has_position():

                old_position = (
                    self.position_manager.get_position()
                )

                if old_position is None:
                    return

                old_side = (
                    old_position["position"]
                )

                old_entry = float(
                    old_position["entry"]
                )

                print()

                print(
                    "******** PAPER REVERSAL ********"
                )

                print(
                    f"Closing existing "
                    f"{old_side}"
                )

                print(
                    f"Old entry: "
                    f"{old_entry:.2f}"
                )

                print(
                    f"Reversal exit: "
                    f"{entry_price:.2f}"
                )

                closed_trade = (
                    self.position_manager.close_position(
                        exit_price=entry_price,
                        reason="REVERSAL",
                    )
                )

                if closed_trade is not None:

                    reversal_pnl = float(
                        closed_trade["pnl"]
                    )

                    total_pnl = (
                        self.position_manager
                        .get_total_pnl()
                    )

                    print(
                        f"Reversal P/L: "
                        f"${reversal_pnl:.2f}"
                    )

                    print(
                        f"Total P/L: "
                        f"${total_pnl:.2f}"
                    )

                    print(
                        "********************************"
                    )

                    # Use the same close path as SL/TP trades so
                    # CSV logging and win/loss statistics stay correct.
                    self.handle_closed_trade(
                        closed_trade
                    )

            # ==================================================
            # CALCULATE RISK
            # ==================================================

            risk_data = (
                self.risk_manager.calculate_position(
                    signal=signal,
                    entry_price=entry_price,
                )
            )

            if risk_data is None:

                print(
                    "[RISK] No risk data returned."
                )

                return

            stop_loss = float(
                risk_data["stop_loss"]
            )

            take_profit = float(
                risk_data["take_profit"]
            )

            quantity = float(
                risk_data["quantity"]
            )

            if quantity <= 0:

                print(
                    "[RISK] Invalid quantity."
                )

                return

            # ==================================================
            # OPEN NEW POSITION
            # ==================================================

            position = (
                self.position_manager.open_position(
                    signal=signal,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    quantity=quantity,
                    candle_time=candle_time,
                )
            )

            if position is None:

                print(
                    "[POSITION] Failed to open position."
                )

                return

            self.save_active_position()

            print()

            print(
                "******** PAPER POSITION ********"
            )

            print(
                f"Side:        "
                f"{signal}"
            )

            print(
                f"Entry:       "
                f"{entry_price:.2f}"
            )

            print(
                f"Stop Loss:   "
                f"{stop_loss:.2f}"
            )

            print(
                f"Take Profit: "
                f"{take_profit:.2f}"
            )

            print(
                f"Quantity:    "
                f"{quantity:.4f}"
            )

            print(
                f"Risk:        "
                f"${float(risk_data['risk_amount']):.2f}"
            )

            print(
                "********************************"
            )

            self.signals.position.emit(
                position
            )

            self.signals.current_pnl.emit(
                0.0
            )

            self.signals.total_pnl.emit(
                self.position_manager.get_total_pnl()
            )

        except Exception:

            traceback.print_exc()

    def handle_price(self, price):

        try:

            price = float(price)

            self.last_price = price

            self.signals.price.emit(
                price
            )

            # Live prices arrive more frequently than closed candles.
            # Check protective exits here so SL/TP can trigger intrabar.
            closed_trade = self.check_position_exit(
                price
            )

            if closed_trade is not None:
                return

            # Keep the PositionManager and GUI unrealized P/L in sync
            # with the latest live market price.
            position = self.position_manager.update_unrealized_pnl(
                price
            )

            if position is not None:
                self.signals.current_pnl.emit(
                    self.position_manager.get_unrealized_pnl()
                )
                self.signals.position.emit(
                    position
                )

        except Exception:

            traceback.print_exc()
    # ==========================================================
    # PROCESS HISTORICAL CANDLE (WARM-UP ONLY)
    # ==========================================================

    async def process_historical_candle(self, candle):

        try:
            if candle is None:
                return

            self.candle_engine.add_candle(
                candle
            )

        except Exception:
            traceback.print_exc()

    # ==========================================================
    # HISTORICAL WARM-UP COMPLETE
    # ==========================================================

    def handle_history_complete(self):

        try:
            candles = self.candle_engine.get_candles()

            if candles:
                # Draw the warmed-up history immediately. Historical candles
                # still do not execute entries/exits or affect trade stats.
                self.signals.chart.emit(candles)

            self.signals.status.emit(
                "Connected - waiting for next closed 3m candle"
            )

            print(
                "[HISTORY] Chart initialized; waiting for live 3m candle",
                flush=True
            )

        except Exception:
            traceback.print_exc()

    # ==========================================================
    # PROCESS CANDLE
    # ==========================================================

    async def process_candle(self, candle):

        try:

            if candle is None:
                return

            print(
                f"[CANDLE RECEIVED] {candle}"
            )

            # ==================================================
            # ADD CANDLE
            # ==================================================

            self.candle_engine.add_candle(
                candle
            )

            # ==================================================
            # CURRENT PRICE
            # ==================================================

            current_price = float(
                candle["close"]
            )

            self.last_price = current_price

            self.signals.price.emit(
                current_price
            )

            # ==================================================
            # CHECK EXIT FIRST
            # ==================================================

            closed_trade = (
                self.check_position_exit(
                    current_price
                )
            )

            if closed_trade is not None:

                self.sync_gui()

            else:

                current_pnl = (
                    self.calculate_current_pnl()
                )

                self.signals.current_pnl.emit(
                    current_pnl
                )

                self.signals.position.emit(
                    self.position_manager.get_position()
                )

                self.signals.total_pnl.emit(
                    self.position_manager.get_total_pnl()
                )

            # ==================================================
            # GENERATE SIGNAL
            # ==================================================

            candles = (
                self.candle_engine.get_candles()
            )

            if candles is None:
                return

            signal_data = (
                self.signal_engine.generate_signal(
                    candles
                )
            )

            # ==================================================
            # WAIT
            # ==================================================

            if signal_data is None:

                print()
                print("[SIGNAL] WAIT")

                return

            # ==================================================
            # SIGNAL DATA
            # ==================================================

            signal = signal_data.get(
                "signal",
                "WAIT",
            )

            reason = signal_data.get(
                "reason",
                "",
            )

            self.signals.signal_reason.emit(reason)

            ema_fast = signal_data.get(
                "ema_fast"
            )

            ema_slow = signal_data.get(
                "ema_slow"
            )

            print()

            print(
                f"[SIGNAL] {signal}"
            )

            print(
                f"[REASON] {reason}"
            )

            if ema_fast is not None:

                print(
                    f"[EMA 5]  "
                    f"{float(ema_fast):.2f}"
                )

            if ema_slow is not None:

                print(
                    f"[EMA 13] "
                    f"{float(ema_slow):.2f}"
                )

            atr = signal_data.get("atr")
            gap_atr = signal_data.get("gap_atr")
            slow_slope = signal_data.get("slow_slope")

            if atr is not None:
                print(f"[ATR 14] {float(atr):.2f}")
            if gap_atr is not None:
                print(f"[EMA GAP] {float(gap_atr):.2f} ATR")
            if slow_slope is not None:
                print(f"[SLOW EMA SLOPE] {float(slow_slope):+.4f}")

            # ==================================================
            # PROCESS SIGNAL
            # ==================================================

            await self.process_signal(
                signal=signal,
                entry_price=current_price,
                candle_time=candle["time"],
            )

        except Exception:

            traceback.print_exc()

        self.signals.chart.emit(
        self.candle_engine.get_candles()
)

    # ==========================================================
    # START
    # ==========================================================

    async def start(self):

        if self.running:
            return

        self.running = True

        print(
            "[BOT] Starting Binance market data..."
        )

        self.signals.status.emit(
            "Connecting to Binance..."
        )

        try:

            await self.websocket_manager.start(
                candle_callback=self.process_candle,
                price_callback=self.handle_price,
                history_callback=self.process_historical_candle,
                history_complete_callback=self.handle_history_complete,
            )

        except asyncio.CancelledError:

            self.running = False

            print(
                "[BOT] WebSocket task cancelled."
            )

            raise

        except Exception as e:

            self.running = False

            self.signals.status.emit(
                "Binance connection error"
            )

            print(
                f"[BOT] WebSocket error: {e}"
            )

            traceback.print_exc()    

    # ==========================================================
    # STOP
    # ==========================================================

    async def stop(self):

        self.running = False

        try:

            stop_method = getattr(
                self.websocket_manager,
                "stop",
                None,
            )

            if stop_method is not None:

                result = stop_method()

                if asyncio.iscoroutine(result):

                    await result

        except Exception:

            traceback.print_exc()


# ==========================================================
# MAIN
# ==========================================================

async def main():

    print("=" * 40)
    print(" TradingBot V9 Starting")
    print("=" * 40)

    window = TradingWindow()
    window.show()

    print("[BOT] GUI started")

    bot = TradingBot(window)
    window.bot = bot

    print("[BOT] Event loop starting...")

    bot_task = asyncio.create_task(bot.start())
    window.bot_task = bot_task

    quit_event = asyncio.Event()
    app = QApplication.instance()
    app.aboutToQuit.connect(quit_event.set)

    try:
        await quit_event.wait()

    finally:
        if hasattr(bot, "stop"):
            await bot.stop()

        if not bot_task.done():
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass


# ==========================================================
# APPLICATION ENTRY
# ==========================================================

if __name__ == "__main__":

    app = QApplication(sys.argv)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    main_task = loop.create_task(main())

    try:
        with loop:
            loop.run_forever()

    except KeyboardInterrupt:
        print("\n[BOT] Stopped by user.")

        if not main_task.done():
            main_task.cancel()

        try:
            with loop:
                loop.run_until_complete(
                    asyncio.gather(main_task, return_exceptions=True)
                )
        except Exception:
            pass

    finally:
        # Drain anything still alive before the qasync loop disappears.
        try:
            pending = [
                task
                for task in asyncio.all_tasks(loop)
                if not task.done()
            ]

            for task in pending:
                task.cancel()

            if pending and not loop.is_closed():
                try:
                    with loop:
                        loop.run_until_complete(
                            asyncio.gather(
                                *pending,
                                return_exceptions=True
                            )
                        )
                except Exception:
                    pass

        except Exception:
            pass

        try:
            app.quit()
        except Exception:
            pass
