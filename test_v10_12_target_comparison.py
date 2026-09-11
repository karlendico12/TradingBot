import contextlib
import io
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from core.execution_v10 import ExecutionConfig
from core.entry_policy_v10_5 import StructuralTargetPlannerV10_5, TargetFeasibilityConfigV10_5
from core.target_comparison_v10_12 import UncappedTargetPlannerV10_12
from terminal_v10_12 import TradingBotV10_12, TradingWindowV10_12
from terminal_v10_5 import PendingActionV10_5
from test_v10_12_integrity import watch, trade
from verify_v10_12 import collect, target_comparison_report


class TargetPolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = TargetFeasibilityConfigV10_5(minimum_room_bps=18, minimum_net_reward_r=.35)
        self.execution = ExecutionConfig()
        self.base = StructuralTargetPlannerV10_5(self.config)
        self.alternate = UncappedTargetPlannerV10_12(self.config)

    def test_no_structure_can_use_fixed_target_despite_low_atr(self):
        for side in ("LONG", "SHORT"):
            with self.subTest(side=side):
                primary = self.base.evaluate(side, 100, self.execution, atr14=.03)
                selected = self.alternate.evaluate(side, 100, self.execution, atr14=.03)
                self.assertFalse(primary.accepted)
                self.assertTrue(selected.accepted)
                self.assertEqual(selected.target_source, "FIXED_2R")
                self.assertEqual(selected.atr_target_market, primary.atr_target_market)

    def test_atr_structure_buffer_is_preserved(self):
        result = self.alternate.evaluate("LONG", 100, self.execution, atr14=1, opposing_levels=[100.3])
        self.assertAlmostEqual(result.structural_target_market, 100.25)
        self.assertEqual(result.target_source, "STRUCTURE")

    def test_nearby_structure_still_blocks_both_sides(self):
        for side, level in (("LONG", 100.1), ("SHORT", 99.9)):
            with self.subTest(side=side):
                result = self.alternate.evaluate(side, 100, self.execution, atr14=.03, opposing_levels=[level])
                self.assertFalse(result.accepted)
                self.assertEqual(result.target_source, "STRUCTURE")

    def test_distant_structure_does_not_extend_fixed_target(self):
        result = self.alternate.evaluate("LONG", 100, self.execution, atr14=.03, opposing_levels=[102])
        self.assertEqual(result.selected_target_market, result.fixed_target_market)

    def test_large_costs_still_reject_fixed_target(self):
        result = self.alternate.evaluate("LONG", 100, replace(self.execution, fee_rate=.003), atr14=.03)
        self.assertFalse(result.accepted)

    def test_default_planner_remains_atr_capped(self):
        result = self.base.evaluate("LONG", 100, self.execution, atr14=.03)
        self.assertEqual(result.target_source, "ATR_CAP")


class ForwardComparisonTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = io.StringIO()
        class Bot(TradingBotV10_12):
            runtime_name = self.temp.name
        with contextlib.redirect_stdout(self.output):
            self.window = TradingWindowV10_12()
            self.bot = Bot(self.window)
        self.peers = self.bot.target_comparison.portfolios
        self.callbacks = self.bot.market_callbacks()
        for portfolio in [self.bot, *self.peers.values()]:
            portfolio.micro_bars.update = Mock(return_value=[])
            portfolio.micro_entry_watch = watch()
            portfolio.micro_entry_watch.state.atr14 = .06
            for _ in range(30):
                portfolio.order_flow.update(trade(59000))

    async def asyncTearDown(self):
        with contextlib.redirect_stdout(self.output):
            await self.bot.stop()
            await self.bot.stop()
        self.window.close()
        self.temp.cleanup()

    async def send(self, t, price=100, eligible=True, maker=False):
        with patch("terminal_v10_12.time.time", return_value=t/1000), contextlib.redirect_stdout(self.output):
            await self.callbacks["trade_callback"](trade(t, price=price, eligible=eligible, maker=maker))
            if eligible:
                await self.callbacks["price_callback"](price, t, "WS_AGGTRADE")

    async def test_only_uncapped_shadow_enters_and_uses_realistic_costs(self):
        await self.send(60100)
        await self.send(60600)
        self.assertFalse(self.bot.position_manager.has_position())
        self.assertFalse(self.peers["BASELINE"].position_manager.has_position())
        position = self.peers["NO_ATR_CAP"].position_manager.get_position()
        self.assertIsNotNone(position)
        self.assertEqual(position["metadata"]["target_policy_mode"], "NO_ATR_CAP")
        self.assertGreater(position["entry"], 100)
        self.assertEqual(position["execution_config"]["fee_rate"], .0004)
        self.assertIn("ROOM_BELOW_MINIMUM", self.window.policy_label.text())
        self.bot._emit_target_comparison(force=True)
        self.assertIn("SHADOW ONLY", self.window.target_comparison_label.text())
        self.assertIn("NO_ATR_CAP", self.window.target_comparison_label.text())

    async def test_shadow_continues_while_actual_position_is_open(self):
        with contextlib.redirect_stdout(self.output):
            self.bot._open_at_observed_price(PendingActionV10_5("OPEN", "LONG", 0, 58000), 100, 59000, "TEST")
        await self.send(60100)
        await self.send(60600)
        self.assertTrue(self.bot.position_manager.has_position())
        self.assertTrue(self.peers["NO_ATR_CAP"].position_manager.has_position())
        self.assertNotEqual(self.bot.store.database_path if hasattr(self.bot.store, "database_path") else self.bot.runtime_name,
                            self.peers["NO_ATR_CAP"].runtime_name)

    async def test_shadow_stop_and_ledger_are_independent(self):
        await self.send(60100)
        await self.send(60600)
        await self.send(61000, price=99)
        data = target_comparison_report(Path(self.temp.name))
        self.assertEqual(data["baseline"]["totals"]["trades"], 0)
        self.assertEqual(data["no_atr_cap"]["totals"]["trades"], 1)
        self.assertLess(data["no_atr_cap"]["totals"]["net_pnl"], 0)
        self.assertEqual(collect(Path(self.temp.name))["totals"]["trades"], 0)
        self.assertGreater(data["no_atr_cap"]["closed_equity_drawdown"], 0)

    async def test_same_target_produces_identical_actual_and_research_results(self):
        for p in [self.bot, *self.peers.values()]:
            p.micro_entry_watch.state.atr14 = .3
        await self.send(60100)
        await self.send(60600)
        await self.send(61000, price=99)
        actual = collect(Path(self.temp.name))["closed_trades"][0]
        for mode in ("baseline", "no_atr_cap"):
            result = collect(Path(self.temp.name) / "target_comparison_v1" / mode)["closed_trades"][0]
            for key in ("entry_utc", "exit_utc", "reason", "fees", "gross_pnl", "net_pnl"):
                self.assertEqual(result[key], actual[key], (mode, key))

    async def test_research_error_disables_comparison_but_keeps_actual_feed(self):
        self.bot.target_comparison.callbacks["BASELINE"]["trade_callback"] = Mock(side_effect=RuntimeError("test failure"))
        await self.send(60100)
        self.assertTrue(self.bot.target_comparison.failed)
        await self.send(60600)
        self.assertFalse(self.bot.position_manager.has_position())
        data = collect(Path(self.temp.name))
        self.assertIn("FAST_ENTRY_REJECTED / ROOM_BELOW_MINIMUM", data["funnel"])
        self.assertIn("TARGET_COMPARISON_FAILED / RuntimeError", data["funnel"])

    async def test_stale_trade_cannot_open_shadow(self):
        await self.send(60100)
        await self.send(60600, eligible=False)
        self.assertFalse(self.peers["NO_ATR_CAP"].position_manager.has_position())

    async def test_history_seed_is_identical_and_independent(self):
        bars = [{"time": 0, "close": 100}, {"time": 60000, "close": 101}]
        self.bot.target_comparison.seed(bars)
        for p in self.peers.values():
            self.assertEqual(p.micro_bars.candles(), bars)
        self.peers["BASELINE"].micro_bars.completed[0]["close"] = 999
        self.assertEqual(self.peers["NO_ATR_CAP"].micro_bars.candles()[0]["close"], 100)

    async def test_context_and_funding_callbacks_are_forwarded(self):
        for p in self.peers.values():
            self.assertFalse(p.market_data.running)
        bar = dict(time=0, close_time=179999, open=100, high=101, low=99, close=100, volume=10, closed=True)
        await self.callbacks["history_callback"](bar)
        for p in self.peers.values():
            self.assertEqual(p.candle_engine.get_candles()[-1]["close"], 100)
        await self.send(60100)
        await self.send(60600)
        await self.callbacks["funding_callback"](60700, .0001, 100)
        self.assertLess(self.peers["NO_ATR_CAP"].position_manager.get_position()["funding_pnl"], 0)
