import unittest

from core.entry_policy_v10_5 import (
    StructuralTargetPlannerV10_5,
    TargetFeasibilityConfigV10_5,
)
from core.execution_v10 import ExecutionConfig
from core.target_policy_v10_11 import CostFeasibleStructuralFallbackV10_11


class _Audit:
    def __init__(self):
        self.events = []

    def record(self, *args, **kwargs):
        self.events.append((args, kwargs))


class _Candles:
    def get_candles(self):
        return [{"time": 1}]


class _Bot:
    def __init__(self):
        self.policy_audit = _Audit()
        self.candle_engine = _Candles()

    def _latest_event_time_ms(self):
        return 2


class StructuralFallbackTests(unittest.TestCase):
    def setUp(self):
        self.config = TargetFeasibilityConfigV10_5(
            maximum_target_atr=2.0,
            minimum_room_bps=18.0,
            minimum_net_reward_r=0.35,
        )
        self.execution = ExecutionConfig()
        self.bot = _Bot()
        self.planner = CostFeasibleStructuralFallbackV10_11(
            self.bot,
            StructuralTargetPlannerV10_5(self.config),
            self.config,
        )

    def test_uses_confirmed_structure_when_atr_cap_is_too_close(self):
        result = self.planner.evaluate(
            "SHORT",
            4408.11,
            self.execution,
            atr14=2.37,
            opposing_levels=[4393.77],
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.target_source, "STRUCTURE")
        self.assertGreaterEqual(result.room_bps, 18.0)
        self.assertGreaterEqual(result.estimated_net_reward_r, 0.35)
        self.assertEqual(len(self.bot.policy_audit.events), 1)

    def test_does_not_invent_target_without_confirmed_structure(self):
        result = self.planner.evaluate(
            "SHORT",
            4408.11,
            self.execution,
            atr14=2.37,
            opposing_levels=[],
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "ROOM_BELOW_MINIMUM")
        self.assertEqual(len(self.bot.policy_audit.events), 0)

    def test_recovers_when_atr_target_is_net_negative_but_structure_passes(self):
        result = self.planner.evaluate(
            "SHORT",
            4405.22,
            self.execution,
            atr14=1.9778571428571792,
            opposing_levels=[4393.77, 4404.93],
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.target_source, "STRUCTURE")
        self.assertGreaterEqual(result.room_bps, 18.0)
        self.assertGreaterEqual(result.estimated_net_reward_r, 0.35)
        self.assertEqual(len(self.bot.policy_audit.events), 1)

    def test_does_not_use_structure_that_fails_economic_gate(self):
        result = self.planner.evaluate(
            "SHORT",
            4408.11,
            self.execution,
            atr14=2.37,
            opposing_levels=[4403.0],
        )
        self.assertFalse(result.accepted)
        self.assertEqual(len(self.bot.policy_audit.events), 0)


if __name__ == "__main__":
    unittest.main()
