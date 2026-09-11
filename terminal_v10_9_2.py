"""TradingBot V10.9.2: regime-aware fast adaptation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox

from terminal_v10 import AsyncBotRunner
from terminal_v10_9_1 import TradingBotV10_9_1, TradingWindowV10_9_1


class TradingWindowV10_9_2(TradingWindowV10_9_1):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TradingBot V10.9.2 - REGIME-AWARE FAST ADAPTATION")
        self.title_label.setText(
            "TradingBot V10.9.2 - REGIME-AWARE FAST ADAPTATION / PAPER ONLY"
        )
        self.policy_label.setText(
            "V10.9.2 Policy: WARMUP | trend-aligned fast entry"
        )

    def update_policy(self, text: str) -> None:
        self.policy_label.setText(f"V10.9.2 Policy: {text}")


class TradingBotV10_9_2(TradingBotV10_9_1):
    runtime_name = "runtime_v10_9_2"
    reversal_regimes = frozenset({"RANGE", "TRANSITION"})

    @classmethod
    def _allow_intrabar_reversal(
        cls,
        base_signal: str,
        snapshot: dict[str, Any],
    ) -> tuple[bool, str]:
        regime = str(snapshot.get("regime") or "UNKNOWN").upper()
        if regime not in cls.reversal_regimes:
            return False, f"REGIME_{regime}"
        return True, f"REGIME_{regime}"

    def print_startup_banner(self) -> None:
        print("=" * 98)
        print("TradingBot V10.9.2 - REGIME-AWARE FAST ADAPTATION / PAPER ONLY")
        print(
            f"fee={self.config.fee_rate:.4%}/side "
            f"slippage={self.config.slippage_bps:.1f}bp/side "
            f"risk={self.config.risk_percent:.2f}% "
            f"max_notional={self.config.max_notional_multiple:.1f}x"
        )
        print("Same-direction entry: first completed signal + live break/flow")
        print("Countertrend override: allowed only in RANGE or TRANSITION")
        print("TREND_DOWN blocks LONG override; TREND_UP blocks SHORT override")
        print("Cost-aware evidence exit: net<=-0.20R AND gross<=-0.05R")
        print("Profit giveback, hard stop/target, and one position retained")
        print("Stale/expired live-watch messages are cleared in the UI")
        print("Daily trade-count cap: OFF; runtime=runtime_v10_9_2")
        print("Do not run another TradingBot version at the same time")
        print("=" * 98)


def main() -> int:
    app = QApplication(sys.argv)
    project = Path(__file__).resolve().parent
    lock = QLockFile(str(project / ".xauusdt_v10_9_2.lock"))
    if not lock.tryLock(100):
        QMessageBox.critical(
            None,
            "TradingBot V10.9.2 already running",
            "Another V10.9.2 instance already owns this project. Close it first.",
        )
        return 2
    window = TradingWindowV10_9_2()
    window.showMaximized()
    bot = TradingBotV10_9_2(window)
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
