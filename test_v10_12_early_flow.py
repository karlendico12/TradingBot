import unittest

from core.early_flow_entry_v10_12 import (
    EarlyFlowEntryConfigV10_12,
    EarlyFlowEntryWatchV10_12,
)
from core.fast_adaptation_v10_9 import FastInitialEntryStateV10_9


class EarlyFlowEntryTests(unittest.TestCase):
    def watch(self, side="LONG"):
        watch = EarlyFlowEntryWatchV10_12(
            EarlyFlowEntryConfigV10_12(
                lifetime_ms=10_000,
                confirmation_ms=500,
                minimum_trade_count_60s=20,
                minimum_abs_flow_imbalance=0.05,
                maximum_chase_bps=5.0,
            )
        )
        watch.arm_from(
            FastInitialEntryStateV10_9(
                side=side,
                candle_time=0,
                decision_time=59_999,
                decision_close=100.0,
                decision_extreme=101.0 if side == "LONG" else 99.0,
                expiry_time=119_999,
                atr14=1.0,
                opposing_levels=(),
            )
        )
        return watch

    def test_triggers_after_half_second_flow_without_extreme_break(self):
        watch = self.watch("LONG")
        first = watch.observe(
            price=100.0,
            event_time=60_100,
            trade_count_60s=100,
            flow_imbalance_60s=0.20,
        )
        second = watch.observe(
            price=100.01,
            event_time=60_600,
            trade_count_60s=100,
            flow_imbalance_60s=0.20,
        )
        self.assertEqual(first.status, "CONFIRMING")
        self.assertTrue(second.trigger)

    def test_alignment_must_be_continuous(self):
        watch = self.watch("LONG")
        watch.observe(
            price=100.0,
            event_time=60_100,
            trade_count_60s=100,
            flow_imbalance_60s=0.20,
        )
        wait = watch.observe(
            price=100.0,
            event_time=60_400,
            trade_count_60s=100,
            flow_imbalance_60s=-0.20,
        )
        restarted = watch.observe(
            price=100.0,
            event_time=60_700,
            trade_count_60s=100,
            flow_imbalance_60s=0.20,
        )
        self.assertEqual(wait.reason, "FLOW_NOT_ALIGNED")
        self.assertEqual(restarted.status, "CONFIRMING")

    def test_cancels_a_chased_move(self):
        watch = self.watch("LONG")
        result = watch.observe(
            price=100.06,
            event_time=60_100,
            trade_count_60s=100,
            flow_imbalance_60s=0.20,
        )
        self.assertTrue(result.cancel)
        self.assertEqual(result.reason, "MOVE_ALREADY_CHASED")


if __name__ == "__main__":
    unittest.main()

