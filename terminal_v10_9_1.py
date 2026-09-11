"""TradingBot V10.9.1: cost-aware correction to V10.9 evidence exits."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox

from terminal_v10 import AsyncBotRunner
from terminal_v10_9 import TradingBotV10_9, TradingWindowV10_9


class TradingWindowV10_9_1(TradingWindowV10_9):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.9.1 - COST-AWARE FAST ADAPTATION")
        self.title_label.setText(
            "TradingBot V10.9.1 - COST-AWARE FAST ADAPTATION / PAPER ONLY"
        )
        self.policy_label.setText(
            "V10.9.1 Policy: WARMUP | gross-aware evidence exit"
        )

    def update_policy(self, text: str) -> None:
        self.policy_label.setText(f"V10.9.1 Policy: {text}")


class TradingBotV10_9_1(TradingBotV10_9):
    runtime_name = "runtime_v10_9_1"

    def print_startup_banner(self) -> None:
        print("=" * 96)
        print("TradingBot V10.9.1 - COST-AWARE FAST ADAPTATION / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Fast entry: first completed 3m direction + live extreme break/flow")
        print("Intrabar override: slow-EMA reclaim + opposite break + strong flow")
        print("V10.8 significant targets, hard stop, and profit guard retained")
        print("V10.9.1 correction: fee-only negative net R cannot trigger loss exit")
        print("Loss exit also requires gross price P/L <= -0.05R")
        print("Profit-giveback exit permits immediate same-direction continuation watch")
        print("Daily trade-count cap: OFF; one actual paper position")
        print("Use runtime_v10_9_1; prior runtime histories remain untouched")
        print("Do not run another TradingBot version at the same time")
        print("=" * 96)


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_9_1.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.9.1 already running",
            "Another V10.9.1 instance already owns this project. Close it first.",
        )
        return 2
    window = TradingWindowV10_9_1()
    window.showMaximized()
    bot = TradingBotV10_9_1(window)
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
