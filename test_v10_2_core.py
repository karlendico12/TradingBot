import tempfile
import unittest
from pathlib import Path

from core.shadow_outcomes_v10_2 import (
    ShadowConfigV10_2,
    ShadowOutcomeEngineV10_2,
)
from core.diagnostics_v10_1 import TradePathTracker
from core.execution_v10 import ExecutionConfig, PaperPositionManagerV10
from terminal_v10_2 import TradingBotV10_2


class ShadowOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.engine = ShadowOutcomeEngineV10_2(
            Path(self.temporary.name) / "shadow.sqlite3",
            ShadowConfigV10_2(horizon_ms=60_000),
        )
        self.candle = {"time": 1, "close_time": 1_000}

    def tearDown(self):
        self.engine.close()
        self.temporary.cleanup()

    @staticmethod
    def trade(event_time, price, *, eligible, source="TEST"):
        return {
            "event_time": event_time,
            "price": price,
            "entry_eligible": eligible,
            "source": source,
        }

    def test_stale_trade_cannot_open_shadow_candidate(self):
        candidate = self.engine.add_candidate(self.candle, "LONG", {"signal": "LONG"})
        self.assertIsNotNone(candidate)
        self.engine.on_trade(self.trade(2_000, 100.0, eligible=False))
        self.assertEqual(self.engine.stats()["pending"], 1)
        self.engine.on_trade(self.trade(6_001, 100.0, eligible=True))
        stats = self.engine.stats()
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["expired"], 1)

    def test_replayed_trade_can_close_already_open_candidate(self):
        candidate_id = self.engine.add_candidate(
            self.candle, "LONG", {"signal": "LONG"}
        )
        self.engine.on_trade(self.trade(1_001, 100.0, eligible=True, source="WS"))
        candidate = self.engine.active[int(candidate_id)]
        target = float(candidate["target_price"])
        self.engine.on_trade(
            self.trade(
                2_000,
                target,
                eligible=False,
                source="REST_REPLAY",
            )
        )
        row = self.engine.connection.execute(
            "SELECT status, exit_reason, exit_source, net_r "
            "FROM shadow_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["exit_reason"], "TARGET")
        self.assertEqual(row["exit_source"], "REST_REPLAY")
        self.assertGreater(row["net_r"], 1.0)

    def test_stop_wins_and_duplicate_identity_is_ignored(self):
        candidate_id = self.engine.add_candidate(
            self.candle, "SHORT", {"signal": "SHORT"}
        )
        duplicate = self.engine.add_candidate(
            self.candle, "SHORT", {"signal": "SHORT"}
        )
        self.assertIsNone(duplicate)
        self.engine.on_trade(self.trade(1_001, 100.0, eligible=True))
        candidate = self.engine.active[int(candidate_id)]
        self.engine.on_trade(
            self.trade(2_000, float(candidate["stop_price"]), eligible=False)
        )
        row = self.engine.connection.execute(
            "SELECT exit_reason, net_r FROM shadow_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()
        self.assertEqual(row["exit_reason"], "STOP")
        self.assertLessEqual(row["net_r"], -0.99)
        self.assertEqual(self.engine.stats()["candidates"], 1)

    def test_restart_censors_unknown_open_path(self):
        self.engine.add_candidate(self.candle, "LONG", {"signal": "LONG"})
        self.engine.on_trade(self.trade(1_001, 100.0, eligible=True))
        self.assertEqual(self.engine.censor_unfinished("RESTART_GAP"), 1)
        self.assertEqual(self.engine.stats()["censored"], 1)


class ReplayedPositionPathTests(unittest.TestCase):
    def test_stale_replayed_trade_can_resolve_existing_stop(self):
        bot = TradingBotV10_2.__new__(TradingBotV10_2)
        bot.position_manager = PaperPositionManagerV10(ExecutionConfig())
        position = bot.position_manager.open_position("LONG", 100.0, 1, 1_000)
        bot.path_tracker = TradePathTracker()
        bot.path_tracker.start(position)
        bot._last_position_path_event_time = 1_000
        closed = []
        bot._record_closed_trade = closed.append

        bot._handle_replayed_position_path(
            {
                "event_time": 2_000,
                "price": float(position["stop_loss"]),
                "source": "REST_AGGTRADE_REPLAY",
                "entry_eligible": False,
            }
        )

        self.assertFalse(bot.position_manager.has_position())
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["reason"], "STOP LOSS")


if __name__ == "__main__":
    unittest.main()
