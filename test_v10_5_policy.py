import tempfile
import unittest
from pathlib import Path

from core.entry_policy_v10_5 import (
    ConfirmedNeutralPolicyV10_5,
    PolicyAuditStoreV10_5,
    StructuralTargetPlannerV10_5,
)
from core.execution_v10 import ExecutionConfig


class TargetPlannerV10_5Tests(unittest.TestCase):
    def setUp(self):
        self.execution = ExecutionConfig()
        self.planner = StructuralTargetPlannerV10_5()

    def test_nearby_long_resistance_rejects_entry(self):
        result = self.planner.evaluate(
            "LONG", 100.0, self.execution, atr14=0.20, opposing_levels=[100.12]
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.target_source, "STRUCTURE")
        self.assertEqual(result.reason, "ROOM_BELOW_MINIMUM")

    def test_long_with_sufficient_room_is_accepted(self):
        result = self.planner.evaluate(
            "LONG", 100.0, self.execution, atr14=0.30, opposing_levels=[100.50]
        )
        self.assertTrue(result.accepted)
        self.assertGreaterEqual(result.room_bps, 30.0)
        self.assertGreaterEqual(result.estimated_net_reward_r, 0.75)

    def test_short_is_symmetric_and_uses_support(self):
        result = self.planner.evaluate(
            "SHORT", 100.0, self.execution, atr14=0.20, opposing_levels=[99.90]
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.target_source, "STRUCTURE")

    def test_atr_cap_can_reject_unrealistic_fixed_target(self):
        result = self.planner.evaluate(
            "LONG", 100.0, self.execution, atr14=0.10, opposing_levels=[]
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.target_source, "ATR_CAP")


class ConfirmedNeutralPolicyTests(unittest.TestCase):
    @staticmethod
    def features(imbalance: float) -> dict:
        return {"trade_count_60s": 20, "flow_imbalance_60s": imbalance}

    def test_opposite_signal_exits_without_reversing(self):
        policy = ConfirmedNeutralPolicyV10_5()
        action = policy.on_decision(
            "SHORT", eligible=True, current_side="LONG", features=self.features(-0.2)
        )
        self.assertEqual(action.action, "EXIT_TO_NEUTRAL")

    def test_reentry_requires_cooldown_and_confirmation(self):
        policy = ConfirmedNeutralPolicyV10_5()
        policy.on_decision(
            "SHORT", eligible=True, current_side="LONG", features=self.features(-0.2)
        )
        policy.mark_signal_exit()
        cooldown = policy.on_decision(
            "SHORT", eligible=True, current_side=None, features=self.features(-0.2)
        )
        self.assertEqual(cooldown.reason, "COOLDOWN")
        confirmed = policy.on_decision(
            "SHORT", eligible=True, current_side=None, features=self.features(-0.2)
        )
        self.assertEqual(confirmed.action, "OPEN")

    def test_confirmation_requires_aligned_flow(self):
        policy = ConfirmedNeutralPolicyV10_5()
        policy.on_decision(
            "LONG", eligible=True, current_side=None, features=self.features(-0.2)
        )
        action = policy.on_decision(
            "LONG", eligible=True, current_side=None, features=self.features(-0.2)
        )
        self.assertEqual(action.reason, "FLOW_NOT_ALIGNED")

    def test_policy_audit_persists_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.sqlite3"
            store = PolicyAuditStoreV10_5(path)
            store.record("ENTRY_REJECTED", "ROOM", event_time=2, side="LONG")
            count = store.connection.execute(
                "SELECT COUNT(*) FROM policy_events"
            ).fetchone()[0]
            store.close()
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
