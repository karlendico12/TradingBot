"""TradingBot V10.3: causal adaptive-policy comparison in forward paper.

The actual V9/V10.2 paper execution is intentionally unchanged. Five parallel
shadow portfolios measure whether fast neutralization and confirmed re-entry
beat immediate reversal after fees and slippage.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox

from core.adaptive_portfolios_v10_3 import (
    AdaptivePortfolioConfigV10_3,
    AdaptivePortfolioEngineV10_3,
)
from terminal_v10 import AsyncBotRunner
from terminal_v10_2 import TradingBotV10_2, TradingWindowV10_2


class AdaptiveSignalsV10_3(QObject):
    updated = pyqtSignal(dict)


class TradingWindowV10_3(TradingWindowV10_2):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.3 - ADAPTIVE POLICY LAB")
        self.title_label.setText("TradingBot V10.3 - ADAPTIVE POLICY LAB / PAPER ONLY")
        self.adaptive_label = QLabel("Adaptive Portfolios: WARMUP")
        chart_index = self.layout.indexOf(self.chart)
        self.layout.insertWidget(chart_index, self.adaptive_label)

    @staticmethod
    def _policy_text(name: str, item: dict[str, Any]) -> str:
        mean = item.get("mean_r")
        pf = item.get("profit_factor")
        mean_text = "--" if mean is None else f"{float(mean):+.3f}R"
        pf_text = "--" if pf is None else f"{float(pf):.2f}"
        active = "*" if item.get("active") else ""
        return (
            f"{name}{active}: N={int(item.get('closed', 0))} "
            f"mean={mean_text} PF={pf_text}"
        )

    def update_adaptive(self, stats: dict[str, dict[str, Any]]) -> None:
        first = " | ".join(
            self._policy_text(name, stats.get(name, {}))
            for name in ("IMMEDIATE", "ADAPTIVE", "HOLD")
        )
        second = " | ".join(
            self._policy_text(name, stats.get(name, {}))
            for name in ("LONG_ONLY", "SHORT_ONLY")
        )
        self.adaptive_label.setText(
            "Adaptive Portfolios (daily cap OFF; * active)\n"
            + first
            + "\n"
            + second
        )


class TradingBotV10_3(TradingBotV10_2):
    runtime_name = "runtime_v10_3"

    def __init__(self, window: TradingWindowV10_3) -> None:
        super().__init__(window)
        runtime_directory = Path(__file__).resolve().parent / self.runtime_name
        config = AdaptivePortfolioConfigV10_3(
            stop_loss_percent=self.config.stop_loss_percent,
            reward_ratio=self.config.reward_ratio,
            fee_rate=self.config.fee_rate,
            slippage_bps=self.config.slippage_bps,
            entry_delay_ms=self.config.max_entry_delay_ms,
            confirmation_bars=2,
        )
        self.adaptive = AdaptivePortfolioEngineV10_3(
            runtime_directory / "adaptive_portfolios_v10_3.sqlite3",
            config,
        )
        self.adaptive_signals = AdaptiveSignalsV10_3()
        self.adaptive_signals.updated.connect(window.update_adaptive)
        self._last_adaptive_emit = 0.0
        self._adaptive_closed = False
        self._emit_adaptive_stats(force=True)

    def print_startup_banner(self) -> None:
        print("=" * 78)
        print("TradingBot V10.3 - ADAPTIVE POLICY LAB / FORWARD PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Actual paper portfolio: V9/V10.2 behavior UNCHANGED")
        print("Adaptive shadow: exit first opposite signal -> neutral")
        print("Adaptive re-entry: 2 consecutive 3m signals + aligned prior-60s flow")
        print("Comparators: IMMEDIATE / ADAPTIVE / HOLD / LONG_ONLY / SHORT_ONLY")
        print("Daily trade-count cap: OFF; daily-loss gate: SHADOW ONLY")
        print("Do not run any other TradingBot version at the same time")
        print("=" * 78)

    def _emit_adaptive_stats(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_adaptive_emit < 0.5:
            return
        self._last_adaptive_emit = now
        self.adaptive_signals.updated.emit(self.adaptive.stats())

    async def process_candle(self, candle: dict[str, Any]) -> None:
        await super().process_candle(candle)
        snapshot = dict(self.latest_snapshot)
        signal = str(snapshot.get("signal", "WAIT"))
        # Preserve the frozen V9 strength fields for later attribution. This is
        # diagnostic only and does not alter the actual V9 decision.
        analysis = self.signal_engine.analyze(self.candle_engine.get_candles())
        snapshot["v9_gap_atr"] = analysis.get("gap_atr")
        snapshot["v9_slow_slope"] = analysis.get("slow_slope")
        snapshot["v9_fast_ema"] = analysis.get("fast_ema")
        snapshot["v9_slow_ema"] = analysis.get("slow_ema")
        eligible = bool(snapshot.get("entry_time_eligible")) and not bool(
            snapshot.get("data_stale")
        )
        self.adaptive.on_decision(
            candle,
            signal,
            snapshot,
            eligible=eligible,
        )
        self._emit_adaptive_stats(force=True)

    async def handle_trade_event(self, trade: dict[str, Any]) -> None:
        await super().handle_trade_event(trade)
        self.adaptive.on_trade(trade)
        self._emit_adaptive_stats()

    async def stop(self) -> None:
        try:
            await super().stop()
        finally:
            if not self._adaptive_closed:
                censored = self.adaptive.censor_open("SHUTDOWN")
                if censored:
                    print(
                        f"[ADAPTIVE] censored {censored} open portfolio(s) at shutdown"
                    )
                self.adaptive.close()
                self._adaptive_closed = True


def main() -> int:
    app = QApplication(sys.argv)
    project_directory = Path(__file__).resolve().parent
    lock = QLockFile(str(project_directory / ".xauusdt_v10_3.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.3 already running",
            "Another V10.3 instance already owns this project. Close it first.",
        )
        return 2

    window = TradingWindowV10_3()
    window.show()
    bot = TradingBotV10_3(window)
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
