import unittest

from core.flow_alignment_watch_v10_7 import FlowAlignmentWatchV10_7


class FlowAlignmentWatchV10_7Tests(unittest.TestCase):
    def arm(self, side="SHORT"):
        watch = FlowAlignmentWatchV10_7()
        watch.arm(
            side=side,
            candle_time=1,
            decision_time=10_000,
            decision_price=100.0,
            atr14=0.2,
            opposing_levels=(99.0,),
        )
        return watch

    def test_enters_after_one_second_persistent_aligned_flow(self):
        watch = self.arm()
        first = watch.observe(
            price=99.98, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=-0.20,
        )
        trigger = watch.observe(
            price=99.97, event_time=11_100,
            trade_count_60s=30, flow_imbalance_60s=-0.15,
        )
        self.assertEqual(first.status, "CONFIRMING")
        self.assertTrue(trigger.trigger)

    def test_alignment_timer_resets_when_flow_flips(self):
        watch = self.arm()
        watch.observe(
            price=99.98, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=-0.20,
        )
        flipped = watch.observe(
            price=99.97, event_time=10_600,
            trade_count_60s=30, flow_imbalance_60s=0.10,
        )
        restarted = watch.observe(
            price=99.96, event_time=11_100,
            trade_count_60s=30, flow_imbalance_60s=-0.20,
        )
        self.assertEqual(flipped.reason, "FLOW_NOT_ALIGNED")
        self.assertEqual(restarted.reason, "FLOW_ALIGNMENT_STARTED")

    def test_does_not_chase_move_over_twenty_bps(self):
        watch = self.arm()
        result = watch.observe(
            price=99.70, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=-0.20,
        )
        self.assertTrue(result.cancel)
        self.assertEqual(result.reason, "MOVE_ALREADY_CHASED")

    def test_adverse_price_does_not_confirm(self):
        watch = self.arm()
        result = watch.observe(
            price=100.01, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=-0.20,
        )
        self.assertFalse(result.trigger)
        self.assertEqual(result.reason, "PRICE_NOT_CONFIRMED")

    def test_long_is_symmetric(self):
        watch = self.arm("LONG")
        watch.observe(
            price=100.01, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=0.20,
        )
        result = watch.observe(
            price=100.02, event_time=11_100,
            trade_count_60s=30, flow_imbalance_60s=0.20,
        )
        self.assertTrue(result.trigger)


if __name__ == "__main__":
    unittest.main()
