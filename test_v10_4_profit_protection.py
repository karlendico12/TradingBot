import unittest

from core.profit_protection_v10_4 import (
    ProfitProtectionConfigV10_4,
    ProfitProtectionV10_4,
)
from core.diagnostics_v10_1 import TradePathTracker
from core.execution_v10 import ExecutionConfig, PaperPositionManagerV10
from terminal_v10_4 import TradingBotV10_4


class ProfitProtectionTests(unittest.TestCase):
    @staticmethod
    def position(entry_time: int = 1_000, pnl: float = 0.0) -> dict:
        return {
            "entry_event_time": entry_time,
            "position": "LONG",
            "planned_stop_loss": 10.0,
            "current_pnl": pnl,
        }

    def test_does_not_arm_below_half_r(self):
        guard = ProfitProtectionV10_4()
        state = guard.observe(self.position(pnl=4.99))
        self.assertFalse(state["armed"])
        self.assertFalse(state["should_exit"])
        self.assertIsNone(state["floor_net_r"])

    def test_arms_at_half_r_and_locks_positive_floor(self):
        guard = ProfitProtectionV10_4()
        state = guard.observe(self.position(pnl=5.0))
        self.assertTrue(state["armed"])
        self.assertAlmostEqual(state["peak_net_r"], 0.5)
        self.assertAlmostEqual(state["floor_net_r"], 0.1)
        self.assertFalse(state["should_exit"])

    def test_trails_peak_and_exits_on_positive_giveback(self):
        guard = ProfitProtectionV10_4()
        guard.observe(self.position(pnl=5.0))
        peak = guard.observe(self.position(pnl=9.0))
        self.assertAlmostEqual(peak["floor_net_r"], 0.5)
        exit_state = guard.observe(self.position(pnl=4.9))
        self.assertTrue(exit_state["should_exit"])
        self.assertAlmostEqual(exit_state["peak_net_r"], 0.9)
        self.assertAlmostEqual(exit_state["floor_net_r"], 0.5)

    def test_floor_never_moves_backwards(self):
        guard = ProfitProtectionV10_4()
        guard.observe(self.position(pnl=10.0))
        high_floor = guard.snapshot()["floor_net_r"]
        guard.observe(self.position(pnl=8.0))
        self.assertEqual(guard.snapshot()["floor_net_r"], high_floor)

    def test_gap_to_negative_is_not_mislabeled_as_profit_exit(self):
        guard = ProfitProtectionV10_4()
        guard.observe(self.position(pnl=8.0))
        state = guard.observe(self.position(pnl=-1.0))
        self.assertTrue(state["armed"])
        self.assertFalse(state["should_exit"])

    def test_new_position_resets_prior_peak(self):
        guard = ProfitProtectionV10_4()
        guard.observe(self.position(entry_time=1_000, pnl=9.0))
        state = guard.observe(self.position(entry_time=2_000, pnl=-1.0))
        self.assertFalse(state["armed"])
        self.assertAlmostEqual(state["peak_net_r"], -0.1)

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            ProfitProtectionConfigV10_4(
                arm_net_r=0.1,
                minimum_locked_net_r=0.1,
            )

    def test_bot_closes_positive_retracement_as_profit_protect(self):
        bot = TradingBotV10_4.__new__(TradingBotV10_4)
        bot.position_manager = PaperPositionManagerV10(ExecutionConfig())
        position = bot.position_manager.open_position("LONG", 100.0, 1, 1_000)
        bot.profit_guard = ProfitProtectionV10_4()
        bot.path_tracker = TradePathTracker()
        bot.path_tracker.start(position)
        bot._emit_profit_guard = lambda *args, **kwargs: None
        closed = []
        bot._record_closed_trade = closed.append

        bot._apply_profit_protection_trade(
            {
                "event_time": 2_000,
                "price": 100.35,
                "source": "TEST",
                "entry_eligible": True,
            }
        )
        self.assertTrue(bot.position_manager.has_position())
        self.assertTrue(bot.profit_guard.armed)

        bot._apply_profit_protection_trade(
            {
                "event_time": 3_000,
                "price": 100.23,
                "source": "TEST",
                "entry_eligible": True,
            }
        )
        self.assertFalse(bot.position_manager.has_position())
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["reason"], "PROFIT PROTECT")
        self.assertGreater(closed[0]["net_pnl"], 0.0)


if __name__ == "__main__":
    unittest.main()
