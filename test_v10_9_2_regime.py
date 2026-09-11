import unittest

from terminal_v10_9_2 import TradingBotV10_9_2


class RegimeAwareOverrideTests(unittest.TestCase):
    def test_trend_down_blocks_long_countertrend_override(self):
        allowed, reason = TradingBotV10_9_2._allow_intrabar_reversal(
            "SHORT", {"regime": "TREND_DOWN"}
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "REGIME_TREND_DOWN")

    def test_trend_up_blocks_short_countertrend_override(self):
        allowed, reason = TradingBotV10_9_2._allow_intrabar_reversal(
            "LONG", {"regime": "TREND_UP"}
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "REGIME_TREND_UP")

    def test_range_allows_guarded_override(self):
        allowed, reason = TradingBotV10_9_2._allow_intrabar_reversal(
            "SHORT", {"regime": "RANGE"}
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "REGIME_RANGE")

    def test_transition_allows_guarded_override(self):
        allowed, reason = TradingBotV10_9_2._allow_intrabar_reversal(
            "LONG", {"regime": "TRANSITION"}
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "REGIME_TRANSITION")

    def test_unknown_blocks_override(self):
        allowed, reason = TradingBotV10_9_2._allow_intrabar_reversal(
            "SHORT", {"regime": "UNKNOWN"}
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "REGIME_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
