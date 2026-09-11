import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from core.early_flow_entry_v10_12 import EarlyFlowEntryConfigV10_12, EarlyFlowEntryWatchV10_12
from core.fast_adaptation_v10_9 import FastInitialEntryStateV10_9
from core.entry_policy_v10_5 import StructuralTargetPlannerV10_5
from terminal_v10_12 import TradingBotV10_12, TradingWindowV10_12
from verify_v10_12 import collect, render


def watch(side="LONG"):
    result = EarlyFlowEntryWatchV10_12(EarlyFlowEntryConfigV10_12())
    result.arm_from(FastInitialEntryStateV10_9(
        side=side, candle_time=0, decision_time=59999, decision_close=100,
        decision_extreme=101 if side == "LONG" else 99,
        expiry_time=119999, atr14=None, opposing_levels=()))
    return result


def trade(t, price=100, maker=False, eligible=True, quantity=1):
    return dict(event_time=t, price=price, buyer_is_maker=maker, quantity=quantity,
                entry_eligible=eligible, source="WS_AGGTRADE")


class RollingContinuityTests(unittest.TestCase):
    def observe(self, w, t, trades, imbalance=.5, count=30, price=100):
        return w.observe(price=price, event_time=t, trade_count_60s=count,
                         flow_imbalance_60s=imbalance, flow_trades=trades)

    def test_count_expiry_between_sparse_prints_restarts_confirmation(self):
        w = watch()
        old = [trade(150)] + [trade(60100) for _ in range(19)]
        self.observe(w, 60100, old, count=20)
        result = self.observe(w, 60800, old[1:] + [trade(60800)], count=20)
        self.assertFalse(result.trigger)
        self.assertEqual(result.reason, "ROLLING_FLOW_EXPIRED_RESTART")
        self.assertEqual(w.state.first_confirmed_time, 60800)
        self.assertEqual(w.confirmation_resets, 1)

    def test_alignment_expiry_even_when_trade_count_remains_sufficient(self):
        w = watch()
        old = [trade(150, quantity=40)] + [trade(60100, maker=True) for _ in range(30)]
        self.observe(w, 60100, old, imbalance=10/70, count=31)
        self.assertEqual(w.flow_valid_until, 60151)
        result = self.observe(w, 60800, old[1:] + [trade(60800, quantity=50)])
        self.assertEqual(result.reason, "ROLLING_FLOW_EXPIRED_RESTART")

    def test_sparse_prints_can_confirm_when_window_stays_valid(self):
        w = watch()
        old = [trade(59000) for _ in range(30)]
        self.observe(w, 60100, old)
        self.assertTrue(self.observe(w, 60800, old + [trade(60800)]).trigger)

    def test_simultaneous_expiries_are_grouped(self):
        w = watch()
        history = [trade(150, quantity=50), trade(150, maker=True, quantity=50)]
        history += [trade(59000) for _ in range(30)]
        self.observe(w, 60100, history)
        self.assertEqual(w.flow_valid_until, 119001)

    def test_short_continuity_is_symmetric(self):
        w = watch("SHORT")
        old = [trade(150, maker=True)] + [trade(60100, maker=True) for _ in range(19)]
        self.observe(w, 60100, old, imbalance=-1, count=20)
        self.assertFalse(self.observe(w, 60800, old[1:] + [trade(60800, maker=True)], imbalance=-1, count=20).trigger)

    def test_out_of_order_print_cannot_complete_hold(self):
        w = watch()
        history = [trade(59000) for _ in range(30)]
        self.observe(w, 60100, history)
        result = self.observe(w, 60050, history)
        self.assertEqual(result.reason, "OUT_OF_ORDER_TRADE")
        self.assertIsNone(w.state.first_confirmed_time)

    def test_adverse_move_is_measured_without_new_strategy_gate(self):
        w = watch()
        history = [trade(59000) for _ in range(30)]
        self.observe(w, 60100, history, price=99.90)
        result = self.observe(w, 60600, history, price=99.80)
        self.assertTrue(result.trigger)
        self.assertAlmostEqual(w.maximum_adverse_bps, 20)

    def test_expiry_and_short_chase(self):
        w = watch("SHORT")
        self.assertEqual(self.observe(w, 70000, []).reason, "EXPIRED")
        w = watch("SHORT")
        self.assertEqual(self.observe(w, 60100, [], price=99.94).reason, "MOVE_ALREADY_CHASED")


class IntegratedBotTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        class Bot(TradingBotV10_12):
            runtime_name = self.temp.name
            enable_target_comparison = False
        self.output = io.StringIO()
        with contextlib.redirect_stdout(self.output):
            self.window = TradingWindowV10_12()
            self.bot = Bot(self.window)
        self.bot.micro_bars.update = Mock(return_value=[])
        self.bot.micro_entry_watch = watch()
        self.bot.target_planner = StructuralTargetPlannerV10_5(self.bot.target_config)
        for _ in range(30):
            self.bot.order_flow.update(trade(59000))

    async def asyncTearDown(self):
        with contextlib.redirect_stdout(self.output):
            await self.bot.stop()
        self.window.close()
        self.temp.cleanup()

    async def send(self, t, **kwargs):
        now = kwargs.pop("now", t)
        with patch("terminal_v10_12.time.time", return_value=now/1000), contextlib.redirect_stdout(self.output):
            await self.bot.handle_trade_event(trade(t, **kwargs))

    async def test_real_pipeline_opens_once_with_costs_and_audited_timing(self):
        await self.send(60100)
        await self.send(60600)
        position = self.bot.position_manager.get_position()
        self.assertIsNotNone(position)
        self.assertEqual(position["version"], "10.12")
        self.assertGreater(position["entry"], 100)
        self.assertEqual(self.bot.config.fee_rate, .0004)
        self.assertFalse(self.bot.daily_loss_gate_enabled)
        await self.send(60900)
        data = collect(Path(self.temp.name))
        self.assertEqual(len(data["attempts"]), 1)
        self.assertEqual(data["active_positions"], 1)
        self.assertEqual(data["attempts"][0]["decision_to_trigger_ms"], 601)
        self.assertEqual(data["attempts"][0]["diagnostics"]["revision"], self.bot.diagnostic_revision)

    async def test_target_rejection_stays_visible_in_full_pipeline(self):
        self.bot.micro_entry_watch.state.atr14 = .06
        await self.send(60100)
        await self.send(60600)
        self.assertFalse(self.bot.position_manager.has_position())
        self.assertIn("ROOM_BELOW_MINIMUM", self.window.policy_label.text())
        self.assertNotIn("expired, invalidated, or rejected", self.window.policy_label.text())
        data = collect(Path(self.temp.name))
        self.assertEqual(data["attempts"][0]["outcome"], "FAST_ENTRY_REJECTED")
        self.assertIn("EARLY_FLOW_OBSERVATION / EARLY_FLOW_CONFIRMED", data["funnel"])

    async def test_ineligible_print_breaks_confirmation(self):
        await self.send(60100)
        await self.send(60400, eligible=False, maker=True)
        await self.send(60700)
        self.assertFalse(self.bot.position_manager.has_position())
        self.assertEqual(self.bot.micro_entry_watch.state.first_confirmed_time, 60700)
        await self.send(61200)
        self.assertTrue(self.bot.position_manager.has_position())

    async def test_stale_flagged_live_print_is_rechecked_at_consumption(self):
        await self.send(60100)
        await self.send(60600, now=90600)
        self.assertFalse(self.bot.position_manager.has_position())
        self.assertIsNone(self.bot.micro_entry_watch.state)
        data = collect(Path(self.temp.name))
        self.assertIn("EARLY_FLOW_WATCH_CANCELLED / EXPIRED_DURING_STALE_DATA", data["funnel"])

    async def test_cancel_reason_remains_visible(self):
        await self.send(60100, price=100.06)
        self.assertIn("MOVE_ALREADY_CHASED", self.window.policy_label.text())

    async def test_recent_print_cannot_trigger_an_expired_wall_clock_watch(self):
        await self.send(69100)
        await self.send(69600, now=70100)
        self.assertFalse(self.bot.position_manager.has_position())
        self.assertIn("EXPIRED_AT_CONSUMPTION", self.window.policy_label.text())

    async def test_replayed_stop_still_closes_existing_position(self):
        await self.send(60100)
        await self.send(60600)
        await self.send(62000, price=99, eligible=False)
        self.assertFalse(self.bot.position_manager.has_position())
        data = collect(Path(self.temp.name))
        self.assertEqual(data["totals"]["trades"], 1)
        self.assertEqual(data["closed_trades"][0]["reason"], "STOP LOSS")

    async def test_completed_micro_signal_replaces_watch_with_context_threshold(self):
        decision = SimpleNamespace(signal="SHORT", reason="test", fast_ema=100,
                                   slow_ema=101, atr14=.5, gap_atr=.2)
        self.bot.micro_engine.analyze = Mock(return_value=decision)
        self.bot.latest_snapshot = {"regime": "TREND_DOWN"}
        self.bot._recent_opposing_levels = Mock(return_value=())
        bar = dict(time=60000, close_time=119999, close=100, high=101, low=99)
        with contextlib.redirect_stdout(self.output):
            handled = self.bot._on_completed_micro_bar(bar, trade(120010), self.bot.order_flow.snapshot(59000))
        self.assertFalse(handled)
        self.assertIsInstance(self.bot.micro_entry_watch, EarlyFlowEntryWatchV10_12)
        self.assertEqual(self.bot.micro_entry_watch.config.minimum_abs_flow_imbalance, .05)
        self.assertEqual(self.bot.micro_entry_watch.state.expiry_time, 129999)

    async def test_evidence_exit_cannot_reenter_on_same_print(self):
        await self.send(60100)
        await self.send(60600)
        self.bot.order_flow.trades.clear()
        for _ in range(30):
            self.bot.order_flow.update(trade(61000, maker=True))
        await self.send(62000, price=99.9, maker=True)
        self.bot.micro_entry_watch = watch("SHORT")
        await self.send(64000, price=99.9, maker=True)
        self.assertFalse(self.bot.position_manager.has_position())
        self.assertIsNone(self.bot.micro_entry_watch.state)
        data = collect(Path(self.temp.name))
        self.assertEqual(data["totals"]["trades"], 1)
        self.assertEqual(data["closed_trades"][0]["reason"], "EVIDENCE FAILURE")
        self.assertLess(data["totals"]["net_pnl"], data["totals"]["gross_pnl"])
        self.assertEqual(data["closed_trades"][0]["decision_to_fill_ms"], 601)

    async def test_fees_alone_do_not_trigger_evidence_failure(self):
        await self.send(60100)
        await self.send(60600)
        self.bot.order_flow.trades.clear()
        for _ in range(30):
            self.bot.order_flow.update(trade(61000, maker=True))
        await self.send(62000, maker=True)
        await self.send(65000, maker=True)
        self.assertTrue(self.bot.position_manager.has_position())


class AuditReadOnlyTests(unittest.TestCase):
    def test_missing_runtime_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "missing"
            data = collect(path)
            self.assertEqual(len(data["missing_databases"]), 3)
            self.assertFalse(path.exists())
            self.assertIn("cannot establish", render(data))
