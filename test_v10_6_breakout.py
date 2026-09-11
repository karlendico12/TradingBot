import unittest

from core.breakout_watch_v10_6 import BreakoutWatchV10_6


class BreakoutWatchV10_6Tests(unittest.TestCase):
    def arm(self, side="SHORT", level=100.0):
        watch = BreakoutWatchV10_6()
        watch.arm(
            side=side,
            level=level,
            candle_time=1,
            decision_time=10_000,
            armed_time=10_010,
            atr14=0.2,
            opposing_levels=(99.0, 100.0),
        )
        return watch

    def test_short_requires_time_confirmation(self):
        watch = self.arm()
        first = watch.observe(
            price=99.97,
            event_time=10_100,
            trade_count_60s=30,
            flow_imbalance_60s=-0.2,
        )
        early = watch.observe(
            price=99.96,
            event_time=10_900,
            trade_count_60s=30,
            flow_imbalance_60s=-0.2,
        )
        trigger = watch.observe(
            price=99.95,
            event_time=11_100,
            trade_count_60s=30,
            flow_imbalance_60s=-0.2,
        )
        self.assertEqual(first.status, "CONFIRMING")
        self.assertEqual(early.reason, "HOLD_TIME")
        self.assertTrue(trigger.trigger)

    def test_breakout_does_not_trigger_against_flow(self):
        watch = self.arm()
        watch.observe(
            price=99.97,
            event_time=10_100,
            trade_count_60s=30,
            flow_imbalance_60s=-0.2,
        )
        result = watch.observe(
            price=99.95,
            event_time=11_100,
            trade_count_60s=30,
            flow_imbalance_60s=0.2,
        )
        self.assertFalse(result.trigger)
        self.assertEqual(result.reason, "FLOW_NOT_ALIGNED")

    def test_reclaim_cancels_short_watch(self):
        watch = self.arm()
        watch.observe(
            price=99.97,
            event_time=10_100,
            trade_count_60s=30,
            flow_imbalance_60s=-0.2,
        )
        result = watch.observe(
            price=100.02,
            event_time=10_500,
            trade_count_60s=30,
            flow_imbalance_60s=-0.2,
        )
        self.assertTrue(result.cancel)
        self.assertEqual(result.reason, "LEVEL_RECLAIMED")

    def test_expiry_cancels_watch(self):
        watch = self.arm()
        result = watch.observe(
            price=99.0,
            event_time=190_001,
            trade_count_60s=30,
            flow_imbalance_60s=-0.2,
        )
        self.assertTrue(result.cancel)
        self.assertEqual(result.reason, "EXPIRED")

    def test_long_is_symmetric(self):
        watch = self.arm(side="LONG")
        watch.observe(
            price=100.03,
            event_time=10_100,
            trade_count_60s=30,
            flow_imbalance_60s=0.2,
        )
        result = watch.observe(
            price=100.04,
            event_time=11_100,
            trade_count_60s=30,
            flow_imbalance_60s=0.2,
        )
        self.assertTrue(result.trigger)


if __name__ == "__main__":
    unittest.main()
