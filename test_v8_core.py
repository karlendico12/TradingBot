import unittest

from core.position_manager import PositionManager
from core.risk_manager import RiskManager


class PositionManagerTests(unittest.TestCase):
    def test_long_stop_loss(self):
        pm = PositionManager()
        pm.open_position("LONG", 100.0, 99.0, 102.0, 10.0, 1)
        trade = pm.check_exit(98.9)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["reason"], "STOP LOSS")
        self.assertLess(trade["pnl"], 0)
        self.assertFalse(pm.has_position())

    def test_long_take_profit(self):
        pm = PositionManager()
        pm.open_position("LONG", 100.0, 99.0, 102.0, 10.0, 1)
        trade = pm.check_exit(102.1)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["reason"], "TAKE PROFIT")
        self.assertGreater(trade["pnl"], 0)

    def test_short_stop_loss(self):
        pm = PositionManager()
        pm.open_position("SHORT", 100.0, 101.0, 98.0, 10.0, 1)
        trade = pm.check_exit(101.1)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["reason"], "STOP LOSS")
        self.assertLess(trade["pnl"], 0)

    def test_short_take_profit(self):
        pm = PositionManager()
        pm.open_position("SHORT", 100.0, 101.0, 98.0, 10.0, 1)
        trade = pm.check_exit(97.9)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["reason"], "TAKE PROFIT")
        self.assertGreater(trade["pnl"], 0)

    def test_unrealized_pnl_updates(self):
        pm = PositionManager()
        pm.open_position("LONG", 100.0, 99.0, 102.0, 2.0, 1)
        pm.update_unrealized_pnl(101.5)
        self.assertAlmostEqual(pm.get_unrealized_pnl(), 3.0)

    def test_same_candle_duplicate_entry_blocked(self):
        pm = PositionManager()
        pm.open_position("LONG", 100.0, 99.0, 102.0, 1.0, 123)
        pm.close_position(100.5, "TEST")
        allowed, _ = pm.can_enter("LONG", 123)
        self.assertFalse(allowed)


class RiskManagerTests(unittest.TestCase):
    def test_default_risk_amount(self):
        rm = RiskManager(account_balance=1000.0, risk_percent=1.0)
        result = rm.calculate("LONG", 100.0)
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["risk_amount"], 10.0)

    def test_configurable_risk_amount(self):
        rm = RiskManager(account_balance=2500.0, risk_percent=2.0)
        result = rm.calculate("SHORT", 100.0)
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["risk_amount"], 50.0)


if __name__ == "__main__":
    unittest.main()
