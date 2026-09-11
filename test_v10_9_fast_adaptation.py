import unittest

from core.fast_adaptation_v10_9 import (
    FastEvidenceExitV10_9,
    FastInitialEntryWatchV10_9,
    FastIntrabarReversalWatchV10_9,
)


class FastInitialEntryTests(unittest.TestCase):
    def watch(self, side="LONG"):
        watch = FastInitialEntryWatchV10_9()
        candle = {
            "time": 1,
            "close_time": 10_000,
            "open": 99.8,
            "high": 100.0,
            "low": 99.5,
            "close": 99.9,
        }
        watch.arm(side=side, candle=candle, atr14=0.3, opposing_levels=(101.0,))
        return watch

    def test_one_bar_long_enters_after_live_break_and_hold(self):
        watch = self.watch()
        first = watch.observe(
            price=100.02, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=0.2,
        )
        trigger = watch.observe(
            price=100.03, event_time=11_100,
            trade_count_60s=30, flow_imbalance_60s=0.2,
        )
        self.assertEqual(first.status, "CONFIRMING")
        self.assertTrue(trigger.trigger)

    def test_entry_does_not_chase(self):
        watch = self.watch()
        result = watch.observe(
            price=100.13, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=0.2,
        )
        self.assertTrue(result.cancel)
        self.assertEqual(result.reason, "MOVE_ALREADY_CHASED")

    def test_entry_requires_decision_extreme_break(self):
        watch = self.watch()
        result = watch.observe(
            price=100.005, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=0.2,
        )
        self.assertEqual(result.reason, "DECISION_EXTREME_NOT_BROKEN")

    def test_short_entry_is_symmetric(self):
        watch = self.watch("SHORT")
        first = watch.observe(
            price=99.48, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=-0.20,
        )
        trigger = watch.observe(
            price=99.47, event_time=11_100,
            trade_count_60s=30, flow_imbalance_60s=-0.20,
        )
        self.assertEqual(first.status, "CONFIRMING")
        self.assertTrue(trigger.trigger)


class FastEvidenceExitTests(unittest.TestCase):
    @staticmethod
    def position(pnl: float, side="LONG"):
        return {
            "entry_event_time": 10_000,
            "position": side,
            "planned_stop_loss": 10.0,
            "current_pnl": pnl,
            "entry": 100.0,
            "current_price": 99.0 if side == "LONG" else 101.0,
            "quantity": 1.0,
        }

    def test_losing_long_exits_after_persistent_sell_flow(self):
        guard = FastEvidenceExitV10_9()
        first = guard.observe(
            position=self.position(-2.1), event_time=11_000,
            trade_count_60s=30, flow_imbalance_60s=-0.2,
        )
        trigger = guard.observe(
            position=self.position(-2.2), event_time=13_000,
            trade_count_60s=30, flow_imbalance_60s=-0.2,
        )
        self.assertEqual(first.status, "CONFIRMING")
        self.assertTrue(trigger.trigger)

    def test_profitable_giveback_can_exit_before_half_r_guard(self):
        guard = FastEvidenceExitV10_9()
        guard.observe(
            position=self.position(2.5), event_time=11_000,
            trade_count_60s=30, flow_imbalance_60s=0.2,
        )
        guard.observe(
            position=self.position(0.4), event_time=12_000,
            trade_count_60s=30, flow_imbalance_60s=-0.2,
        )
        trigger = guard.observe(
            position=self.position(0.3), event_time=14_000,
            trade_count_60s=30, flow_imbalance_60s=-0.2,
        )
        self.assertTrue(trigger.trigger)
        self.assertEqual(trigger.reason, "GIVEBACK_EVIDENCE_CONFIRMED")

    def test_adverse_flow_alone_does_not_exit_a_healthy_trade(self):
        guard = FastEvidenceExitV10_9()
        result = guard.observe(
            position=self.position(1.0), event_time=11_000,
            trade_count_60s=30, flow_imbalance_60s=-0.2,
        )
        self.assertFalse(result.trigger)

    def test_favorable_gross_short_is_not_a_loss_due_to_fees(self):
        guard = FastEvidenceExitV10_9()
        position = self.position(-2.1, "SHORT")
        position["current_price"] = 99.9
        first = guard.observe(
            position=position, event_time=11_000,
            trade_count_60s=30, flow_imbalance_60s=0.20,
        )
        position["current_pnl"] = -2.2
        second = guard.observe(
            position=position, event_time=13_000,
            trade_count_60s=30, flow_imbalance_60s=0.20,
        )
        self.assertFalse(first.trigger)
        self.assertFalse(second.trigger)
        self.assertEqual(second.reason, "EXIT_EVIDENCE_NOT_MET")

    def test_losing_short_exits_on_persistent_buy_flow(self):
        guard = FastEvidenceExitV10_9()
        guard.observe(
            position=self.position(-2.1, "SHORT"), event_time=11_000,
            trade_count_60s=30, flow_imbalance_60s=0.20,
        )
        trigger = guard.observe(
            position=self.position(-2.2, "SHORT"), event_time=13_000,
            trade_count_60s=30, flow_imbalance_60s=0.20,
        )
        self.assertTrue(trigger.trigger)


class FastIntrabarReversalTests(unittest.TestCase):
    def watch(self, base_side="SHORT"):
        watch = FastIntrabarReversalWatchV10_9()
        candle = {
            "time": 1,
            "close_time": 10_000,
            "open": 99.8,
            "high": 100.0,
            "low": 99.5,
            "close": 99.7,
        }
        watch.arm(
            base_side=base_side,
            candle=candle,
            slow_ema=99.8,
            atr14=0.3,
            opposing_levels=(101.0,),
        )
        return watch

    def test_short_bias_can_flip_to_long_after_strong_live_confirmation(self):
        watch = self.watch()
        first = watch.observe(
            price=100.02, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=0.20,
        )
        trigger = watch.observe(
            price=100.03, event_time=12_100,
            trade_count_60s=30, flow_imbalance_60s=0.20,
        )
        self.assertEqual(first.status, "CONFIRMING")
        self.assertTrue(trigger.trigger)

    def test_reversal_requires_both_ema_reclaim_and_extreme_break(self):
        watch = self.watch()
        result = watch.observe(
            price=99.99, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=0.20,
        )
        self.assertEqual(result.reason, "REVERSAL_PRICE_NOT_CONFIRMED")

    def test_reversal_requires_stronger_flow_than_normal_entry(self):
        watch = self.watch()
        result = watch.observe(
            price=100.02, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=0.10,
        )
        self.assertEqual(result.reason, "REVERSAL_FLOW_NOT_ALIGNED")

    def test_long_bias_can_flip_to_short_symmetrically(self):
        watch = self.watch("LONG")
        first = watch.observe(
            price=99.48, event_time=10_100,
            trade_count_60s=30, flow_imbalance_60s=-0.20,
        )
        trigger = watch.observe(
            price=99.47, event_time=12_100,
            trade_count_60s=30, flow_imbalance_60s=-0.20,
        )
        self.assertEqual(first.status, "CONFIRMING")
        self.assertTrue(trigger.trigger)


if __name__ == "__main__":
    unittest.main()
