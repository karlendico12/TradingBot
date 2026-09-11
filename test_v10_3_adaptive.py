import tempfile
import unittest
import sqlite3
from pathlib import Path

from core.adaptive_portfolios_v10_3 import (
    AdaptivePortfolioConfigV10_3,
    AdaptivePortfolioEngineV10_3,
)


class AdaptivePortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "adaptive.sqlite3"
        self.engine = AdaptivePortfolioEngineV10_3(self.path)

    def tearDown(self):
        try:
            self.engine.close()
        except sqlite3.ProgrammingError:  # pragma: no cover - closed in one test
            pass
        self.temporary.cleanup()

    @staticmethod
    def candle(index: int) -> dict:
        close_time = index * 10_000
        return {"time": close_time - 180_000, "close_time": close_time}

    @staticmethod
    def features(flow: float) -> dict:
        return {
            "flow_imbalance_60s": flow,
            "trade_count_60s": 100,
        }

    @staticmethod
    def trade(event_time: int, price: float = 100.0, eligible: bool = True) -> dict:
        return {
            "event_time": event_time,
            "price": price,
            "source": "TEST",
            "entry_eligible": eligible,
        }

    def decide(self, index: int, signal: str, flow: float) -> None:
        self.engine.on_decision(
            self.candle(index),
            signal,
            self.features(flow),
            eligible=True,
        )

    def test_immediate_reverses_but_hold_and_directional_do_not(self):
        self.decide(1, "LONG", 0.2)
        self.engine.on_trade(self.trade(10_001))
        self.assertEqual(self.engine.positions["IMMEDIATE"]["side"], "LONG")
        self.assertEqual(self.engine.positions["HOLD"]["side"], "LONG")
        self.assertEqual(self.engine.positions["LONG_ONLY"]["side"], "LONG")

        self.decide(2, "SHORT", -0.2)
        self.engine.on_trade(self.trade(20_001))
        self.assertEqual(self.engine.positions["IMMEDIATE"]["side"], "SHORT")
        self.assertEqual(self.engine.positions["HOLD"]["side"], "LONG")
        self.assertEqual(self.engine.positions["LONG_ONLY"]["side"], "LONG")
        self.assertEqual(self.engine.positions["SHORT_ONLY"]["side"], "SHORT")
        row = self.engine.connection.execute(
            "SELECT exit_reason, net_r FROM adaptive_trades "
            "WHERE policy='IMMEDIATE' AND status='CLOSED'"
        ).fetchone()
        self.assertEqual(row["exit_reason"], "REVERSAL")
        self.assertLess(row["net_r"], 0.0)

    def test_adaptive_exits_first_flip_then_requires_second_aligned_signal(self):
        self.decide(1, "LONG", 0.2)
        self.engine.on_trade(self.trade(10_001))
        self.assertNotIn("ADAPTIVE", self.engine.positions)
        self.decide(2, "LONG", 0.1)
        self.engine.on_trade(self.trade(20_001))
        self.assertEqual(self.engine.positions["ADAPTIVE"]["side"], "LONG")

        self.decide(3, "SHORT", -0.3)
        self.engine.on_trade(self.trade(30_001))
        self.assertNotIn("ADAPTIVE", self.engine.positions)
        row = self.engine.connection.execute(
            "SELECT exit_reason FROM adaptive_trades "
            "WHERE policy='ADAPTIVE' AND status='CLOSED'"
        ).fetchone()
        self.assertEqual(row["exit_reason"], "SIGNAL_TO_NEUTRAL")

        self.decide(4, "SHORT", -0.1)
        self.engine.on_trade(self.trade(40_001))
        self.assertEqual(self.engine.positions["ADAPTIVE"]["side"], "SHORT")

    def test_adaptive_rejects_misaligned_flow(self):
        self.decide(1, "SHORT", -0.1)
        self.engine.on_trade(self.trade(10_001))
        self.decide(2, "SHORT", 0.2)
        self.engine.on_trade(self.trade(20_001))
        self.assertNotIn("ADAPTIVE", self.engine.positions)

    def test_stale_trade_cannot_execute_pending_entry(self):
        self.decide(1, "LONG", 0.2)
        self.engine.on_trade(self.trade(10_001, eligible=False))
        self.assertNotIn("IMMEDIATE", self.engine.positions)
        self.engine.on_trade(self.trade(15_001, eligible=True))
        self.assertNotIn("IMMEDIATE", self.engine.positions)
        self.assertNotIn("IMMEDIATE", self.engine.pending)

    def test_replayed_trade_can_stop_an_open_position(self):
        self.decide(1, "LONG", 0.2)
        self.engine.on_trade(self.trade(10_001))
        stop = float(self.engine.positions["IMMEDIATE"]["stop_price"])
        self.engine.on_trade(self.trade(10_500, stop, eligible=False))
        self.assertNotIn("IMMEDIATE", self.engine.positions)
        row = self.engine.connection.execute(
            "SELECT exit_reason, status FROM adaptive_trades "
            "WHERE policy='IMMEDIATE'"
        ).fetchone()
        self.assertEqual(dict(row), {"exit_reason": "STOP", "status": "CLOSED"})

    def test_no_daily_trade_count_cap(self):
        for index in range(1, 14):
            signal = "LONG" if index % 2 else "SHORT"
            flow = 0.2 if signal == "LONG" else -0.2
            self.decide(index, signal, flow)
            self.engine.on_trade(self.trade(index * 10_000 + 1))
        stats = self.engine.stats()["IMMEDIATE"]
        self.assertEqual(stats["closed"], 12)
        self.assertTrue(stats["active"])

    def test_restart_censors_unknown_open_path(self):
        self.decide(1, "LONG", 0.2)
        self.engine.on_trade(self.trade(10_001))
        self.engine.close()
        replacement = AdaptivePortfolioEngineV10_3(self.path)
        try:
            row = replacement.connection.execute(
                "SELECT status, exit_reason FROM adaptive_trades "
                "WHERE policy='IMMEDIATE'"
            ).fetchone()
            self.assertEqual(row["status"], "CENSORED")
            self.assertEqual(row["exit_reason"], "RESTART_GAP")
        finally:
            replacement.close()


if __name__ == "__main__":
    unittest.main()
