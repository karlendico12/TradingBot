"""TradingBot V10.11: one-minute execution with structural target fallback."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.target_policy_v10_11 import CostFeasibleStructuralFallbackV10_11
from terminal_v10 import AsyncBotRunner
from terminal_v10_10 import TradingBotV10_10, TradingWindowV10_10


class TradingWindowV10_11(TradingWindowV10_10):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.11 - COST-FEASIBLE STRUCTURAL TARGET")
        self.title_label.setText(
            "TradingBot V10.11 - COST-FEASIBLE STRUCTURAL TARGET / PAPER ONLY"
        )
        self.policy_label.setText(
            "V10.11 Policy: WARMUP | loading completed 1m history"
        )

    def update_policy(self, text: str) -> None:
        self.policy_label.setText(f"V10.11 Policy: {text}")


class TradingBotV10_11(TradingBotV10_10):
    runtime_name = "runtime_v10_11"
    micro_log_version = "V10.11"

    def __init__(self, window: TradingWindowV10_11) -> None:
        super().__init__(window)
        self.target_planner = CostFeasibleStructuralFallbackV10_11(
            self,
            self.target_planner,
            self.target_config,
        )
        self.signals.status.emit(
            "V10.11 ready | 1m execution + confirmed structural target fallback"
        )
        self._emit_policy(
            "READY | 1m execution + confirmed structural target fallback"
        )

    def print_startup_banner(self) -> None:
        print("=" * 100)
        print("TradingBot V10.11 - COST-FEASIBLE STRUCTURAL TARGET / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Decision/entry/exit: unchanged V10.10 completed-1m + live aggTrade")
        print("Primary target: unchanged nearest fixed / structure / 2-ATR cap")
        print("Fallback: confirmed structure only when ATR cap fails economic gates")
        print("Economic gates retained: >=18bps room and >=0.35 estimated net R")
        print("No structural level or infeasible structural level: reject the entry")
        print("Daily trade-count cap: OFF; one paper position; no same-print flip")
        print("runtime=runtime_v10_11; do not combine results with V10.10")
        print("=" * 100)


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_11.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.11 already running",
            "Another V10.11 instance already owns this project. Close it first.",
        )
        return 2
    window = TradingWindowV10_11()
    window.showMaximized()
    bot = TradingBotV10_11(window)
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
