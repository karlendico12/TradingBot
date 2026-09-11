"""TradingBot V10.4: V10.3 paper lab plus all-in-R profit protection."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.profit_protection_v10_4 import (
    ProfitProtectionConfigV10_4,
    ProfitProtectionV10_4,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_3 import TradingBotV10_3, TradingWindowV10_3


class ProfitProtectionSignalsV10_4(QObject):
    updated = pyqtSignal(dict)


class TradingWindowV10_4(TradingWindowV10_3):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.4 - COST-AWARE PROFIT PROTECTION")
        self.title_label.setText(
            "TradingBot V10.4 - COST-AWARE PROFIT PROTECTION / PAPER ONLY"
        )
        self.profit_guard_label = QLabel("Profit Guard: FLAT")
        chart_index = self.layout.indexOf(self.chart)
        self.layout.insertWidget(chart_index, self.profit_guard_label)
        self._rebuild_dashboard()

    @staticmethod
    def _card(object_name: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName(object_name)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        return frame, layout

    @staticmethod
    def _scrolling_tab(labels: list[QLabel]) -> QScrollArea:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        for label in labels:
            label.setWordWrap(True)
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(label)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _rebuild_dashboard(self) -> None:
        # All inherited widgets are reused; only their layout changes. Trading
        # callbacks and chart objects remain exactly the same.
        while self.layout.count():
            self.layout.takeAt(0)
        self.layout.setContentsMargins(12, 10, 12, 12)
        self.layout.setSpacing(8)
        self.setMinimumSize(1200, 700)
        self.resize(1500, 900)

        header, header_layout = self._card("headerCard")
        self.title_label.setObjectName("heroTitle")
        self.title_label.setWordWrap(True)
        header_layout.addWidget(self.title_label)
        self.status_label.setObjectName("statusLine")
        self.status_label.setWordWrap(True)
        header_layout.addWidget(self.status_label)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        for label, name in (
            (self.price_label, "priceMetric"),
            (self.signal_label, "signalMetric"),
            (self.position_label, "positionMetric"),
            (self.current_pnl_label, "pnlMetric"),
        ):
            label.setObjectName(name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(42)
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            metrics.addWidget(label, 1)
        header_layout.addLayout(metrics)
        self.layout.addWidget(header)

        guard_card, guard_layout = self._card("profitGuardCard")
        self.profit_guard_label.setObjectName("profitGuard")
        self.profit_guard_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.profit_guard_label.setWordWrap(True)
        guard_layout.addWidget(self.profit_guard_label)
        self.layout.addWidget(guard_card)

        chart_panel, chart_layout = self._card("chartCard")
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        chart_title = QLabel("XAUUSDT · 3-minute chart")
        chart_title.setObjectName("sectionTitle")
        toolbar.addWidget(chart_title)
        toolbar.addStretch(1)
        help_text = QLabel("Drag to pan  •  Wheel to zoom")
        help_text.setObjectName("mutedText")
        toolbar.addWidget(help_text)
        for title, callback in (
            ("Latest 60", lambda: self._show_latest(60)),
            ("Latest 120", lambda: self._show_latest(120)),
            ("Follow Live", self._follow_live),
            ("Reset Y", self._reset_y),
        ):
            button = QPushButton(title)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        chart_layout.addLayout(toolbar)
        self.chart.setMinimumHeight(520)
        self.chart.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        chart_layout.addWidget(self.chart, 1)

        self.side_tabs = QTabWidget()
        self.side_tabs.setObjectName("sideTabs")
        self.side_tabs.setMinimumWidth(470)
        self.side_tabs.addTab(
            self._scrolling_tab(
                [
                    self.entry_label,
                    self.stop_label,
                    self.tp_label,
                    self.quantity_label,
                    self.signal_reason_label,
                ]
            ),
            "Position",
        )
        self.side_tabs.addTab(
            self._scrolling_tab(
                [
                    self.total_pnl_label,
                    self.stats_title,
                    self.trades_label,
                    self.wins_label,
                    self.losses_label,
                    self.winrate_label,
                    self.last_trade_label,
                ]
            ),
            "Performance",
        )
        self.side_tabs.addTab(
            self._scrolling_tab(
                [
                    self.structure_label,
                    self.market_label,
                    self.flow_label,
                    self.safety_label,
                    self.feed_health_label,
                ]
            ),
            "Diagnostics",
        )
        self.side_tabs.addTab(
            self._scrolling_tab(
                [
                    self.shadow_label,
                    self.adaptive_label,
                ]
            ),
            "Research",
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(chart_panel)
        splitter.addWidget(self.side_tabs)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1100, 480])
        self.layout.addWidget(splitter, 1)
        self.main_splitter = splitter

        axis_font = QFont("Segoe UI", 10)
        for axis_name in ("left", "bottom"):
            axis = self.chart.getAxis(axis_name)
            if hasattr(axis, "setTickFont"):
                axis.setTickFont(axis_font)

        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #10141c;
                color: #e8edf5;
                font-family: "Segoe UI";
                font-size: 14px;
            }
            QFrame#headerCard, QFrame#profitGuardCard, QFrame#chartCard {
                background: #171d27;
                border: 1px solid #2a3443;
                border-radius: 9px;
            }
            QLabel#heroTitle {
                color: #ffffff;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#statusLine, QLabel#mutedText {
                color: #9eabc0;
            }
            QLabel#priceMetric, QLabel#signalMetric,
            QLabel#positionMetric, QLabel#pnlMetric {
                background: #202938;
                border: 1px solid #334158;
                border-radius: 7px;
                color: #f7f9fc;
                font-size: 16px;
                font-weight: 650;
                padding: 6px 10px;
            }
            QLabel#profitGuard {
                color: #ffc857;
                font-size: 16px;
                font-weight: 700;
                padding: 4px;
            }
            QLabel#sectionTitle {
                color: #ffffff;
                font-size: 16px;
                font-weight: 700;
            }
            QPushButton {
                background: #263247;
                border: 1px solid #3a4b67;
                border-radius: 6px;
                color: #edf3ff;
                padding: 6px 11px;
            }
            QPushButton:hover { background: #32415a; }
            QPushButton:pressed { background: #1f2939; }
            QTabWidget::pane {
                border: 1px solid #2a3443;
                background: #171d27;
                border-radius: 7px;
            }
            QTabBar::tab {
                background: #202938;
                color: #aeb9c9;
                padding: 9px 12px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #2f6fed;
                color: white;
            }
            QScrollArea { background: #171d27; }
            QSplitter::handle { background: #2a3443; width: 5px; }
            """
        )

    def _show_latest(self, count: int) -> None:
        total = len(self.last_candles)
        if total < 2:
            return
        self.chart_user_navigated = True
        self.chart.setXRange(max(0, total - int(count)), total + 2, padding=0)
        self.chart.enableAutoRange(axis="y")

    def _follow_live(self) -> None:
        self.chart_user_navigated = False
        self._show_latest(120)
        self.chart_user_navigated = False

    def _reset_y(self) -> None:
        self.chart.enableAutoRange(axis="y")

    @staticmethod
    def _r_text(value: Any) -> str:
        return "--" if value is None else f"{float(value):+.3f}R"

    def update_profit_guard(self, state: dict[str, Any]) -> None:
        if state.get("entry_event_time") is None:
            self.profit_guard_label.setText(
                "Profit Guard: FLAT | arm=+0.50R lock=+0.10R giveback=0.40R"
            )
            self.profit_guard_label.setStyleSheet("color: #9eabc0;")
            return
        status = "ARMED" if state.get("armed") else "TRACKING"
        self.profit_guard_label.setText(
            "Profit Guard: "
            f"{status} {state.get('side', '--')} | "
            f"now={self._r_text(state.get('last_net_r'))} "
            f"peak={self._r_text(state.get('peak_net_r'))} "
            f"floor={self._r_text(state.get('floor_net_r'))}"
        )
        self.profit_guard_label.setStyleSheet(
            "color: #38d996;" if state.get("armed") else "color: #ffc857;"
        )

    def update_signal(self, signal: str) -> None:
        super().update_signal(signal)
        color = {
            "LONG": "#38d996",
            "SHORT": "#ff6b6b",
            "WAIT": "#ffc857",
        }.get(str(signal), "#e8edf5")
        self.signal_label.setStyleSheet(f"color: {color};")

    def update_position(self, position: dict[str, Any] | None) -> None:
        super().update_position(position)
        side = "NONE" if position is None else str(position.get("position", "NONE"))
        color = "#38d996" if side == "LONG" else "#ff6b6b" if side == "SHORT" else "#9eabc0"
        self.position_label.setStyleSheet(f"color: {color};")

    def update_current_pnl(self, pnl: float) -> None:
        super().update_current_pnl(pnl)
        value = float(pnl)
        color = "#38d996" if value > 0 else "#ff6b6b" if value < 0 else "#e8edf5"
        self.current_pnl_label.setStyleSheet(f"color: {color};")

    def update_total_pnl(self, pnl: float) -> None:
        super().update_total_pnl(pnl)
        value = float(pnl)
        color = "#38d996" if value > 0 else "#ff6b6b" if value < 0 else "#e8edf5"
        self.total_pnl_label.setStyleSheet(
            f"color: {color}; font-size: 18px; font-weight: 700;"
        )


class TradingBotV10_4(TradingBotV10_3):
    runtime_name = "runtime_v10_4"

    def __init__(self, window: TradingWindowV10_4) -> None:
        super().__init__(window)
        self.profit_guard = ProfitProtectionV10_4(
            ProfitProtectionConfigV10_4(
                arm_net_r=0.50,
                minimum_locked_net_r=0.10,
                trailing_giveback_r=0.40,
            )
        )
        self.profit_guard_signals = ProfitProtectionSignalsV10_4()
        self.profit_guard_signals.updated.connect(window.update_profit_guard)
        self._last_profit_guard_emit = 0.0
        self._emit_profit_guard(force=True)

    def print_startup_banner(self) -> None:
        print("=" * 80)
        print("TradingBot V10.4 - COST-AWARE PROFIT PROTECTION / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Entry signal: frozen V9/V10.3 completed-3m decision")
        print("Execution: next fresh aggregate trade, maximum delay 5 seconds")
        print("Profit guard: arm +0.50 net R; lock +0.10R; trail 0.40R from peak")
        print("Original stop/target and V10.3 adaptive shadow portfolios retained")
        print("Daily trade-count cap: OFF; one actual paper position at a time")
        print("Do not run any other TradingBot version at the same time")
        print("=" * 80)

    def _emit_profit_guard(
        self,
        state: dict[str, Any] | None = None,
        *,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and now - self._last_profit_guard_emit < 0.10:
            return
        self._last_profit_guard_emit = now
        self.profit_guard_signals.updated.emit(state or self.profit_guard.snapshot())

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
        self.profit_guard.reset()
        position = self.position_manager.get_position()
        if position is not None:
            state = self.profit_guard.observe(position)
            metadata = dict(position.get("metadata", {}))
            metadata["profit_protection_config"] = state["config"]
            position["metadata"] = metadata
            self.store.save_position(position)
            self._emit_profit_guard(state, force=True)

    def _record_closed_trade(self, trade: dict[str, Any] | None) -> None:
        if trade is None:
            return
        metadata = dict(trade.get("metadata", {}))
        metadata["profit_protection"] = self.profit_guard.snapshot()
        trade["metadata"] = metadata
        super()._record_closed_trade(trade)
        self.profit_guard.reset()
        self._emit_profit_guard(force=True)

    async def handle_trade_event(self, trade: dict[str, Any]) -> None:
        await super().handle_trade_event(trade)
        self._apply_profit_protection_trade(trade)

    def _apply_profit_protection_trade(self, trade: dict[str, Any]) -> None:
        position = self.position_manager.get_position()
        if position is None:
            if self.profit_guard.entry_event_time is not None:
                self.profit_guard.reset()
                self._emit_profit_guard(force=True)
            return

        event_time = int(trade["event_time"])
        if event_time <= int(position["entry_event_time"]):
            return
        price = float(trade["price"])
        updated = self.position_manager.update_unrealized_pnl(price)
        if updated is None:
            return
        state = self.profit_guard.observe(updated)
        self._emit_profit_guard(state)
        if not bool(state["should_exit"]):
            return

        # Fresh paths have not yet reached handle_price. Replayed paths were
        # already observed by V10.2's recovery handler.
        if bool(trade.get("entry_eligible", False)):
            self.path_tracker.observe(price, event_time)
        closed = self.position_manager.close_position(
            price,
            "PROFIT PROTECT",
            event_time,
            str(trade.get("source", "UNKNOWN")),
        )
        self._record_closed_trade(closed)


def main() -> int:
    app = QApplication(sys.argv)
    project_directory = Path(__file__).resolve().parent
    lock = QLockFile(str(project_directory / ".xauusdt_v10_4.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.4 already running",
            "Another V10.4 instance already owns this project. Close it first.",
        )
        return 2

    window = TradingWindowV10_4()
    window.showMaximized()
    bot = TradingBotV10_4(window)
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
