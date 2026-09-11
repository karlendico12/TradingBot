import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from core.execution_v10 import (
    ExecutionConfig,
    PaperPositionManagerV10,
    PendingEntry,
    candle_entry_is_timely,
)
from core.market_data_v10 import BinanceMarketDataV10, interval_to_milliseconds
from core.paper_store_v10 import PaperStoreV10


class ExecutionV10Tests(unittest.TestCase):
    def setUp(self):
        self.config = ExecutionConfig(
            starting_balance=1_000.0,
            risk_percent=1.0,
            stop_loss_percent=0.002,
            reward_ratio=2.0,
            max_notional_multiple=3.0,
            fee_rate=0.0004,
            slippage_bps=1.0,
        )

    def test_notional_is_capped_at_three_times_equity(self):
        manager = PaperPositionManagerV10(self.config)
        position = manager.open_position("LONG", 100.0, 1, 2)
        self.assertLessEqual(position["notional"], 3_000.0 + 1e-8)
        self.assertLessEqual(position["planned_stop_loss"], 10.0 + 1e-8)

    def test_long_entry_and_exit_receive_adverse_slippage(self):
        manager = PaperPositionManagerV10(self.config)
        position = manager.open_position(
            "LONG", 100.0, 1, 2, "REST_AGGTRADE_REPLAY"
        )
        self.assertGreater(position["entry"], 100.0)
        trade = manager.close_position(101.0, "TEST", 3, "WS_AGGTRADE")
        self.assertLess(trade["exit"], 101.0)
        self.assertEqual(trade["entry_source"], "REST_AGGTRADE_REPLAY")
        self.assertEqual(trade["exit_source"], "WS_AGGTRADE")
        self.assertAlmostEqual(
            trade["net_pnl"],
            trade["gross_pnl"] - trade["fees"] + trade["funding_pnl"],
        )

    def test_short_entry_and_exit_receive_adverse_slippage(self):
        manager = PaperPositionManagerV10(self.config)
        position = manager.open_position("SHORT", 100.0, 1, 2)
        self.assertLess(position["entry"], 100.0)
        trade = manager.close_position(99.0, "TEST", 3)
        self.assertGreater(trade["exit"], 99.0)

    def test_stop_loss_includes_fees_and_slippage(self):
        manager = PaperPositionManagerV10(self.config)
        position = manager.open_position("LONG", 100.0, 1, 2)
        trade = manager.check_exit(position["stop_loss"], 3)
        self.assertIsNotNone(trade)
        self.assertAlmostEqual(
            -trade["net_pnl"],
            position["planned_stop_loss"],
            places=8,
        )

    def test_equity_drives_next_position_size(self):
        manager = PaperPositionManagerV10(self.config)
        first = manager.open_position("LONG", 100.0, 1, 2)
        manager.close_position(102.0, "TEST", 3)
        second = manager.open_position("LONG", 100.0, 4, 5)
        self.assertGreater(second["notional"], first["notional"])

    def test_funding_sign_is_directional_and_deduplicated(self):
        long_manager = PaperPositionManagerV10(self.config)
        long_manager.open_position("LONG", 100.0, 1, 100)
        first = long_manager.apply_funding(200, 0.001, 100.0)
        duplicate = long_manager.apply_funding(200, 0.001, 100.0)
        self.assertLess(first, 0)
        self.assertEqual(duplicate, 0)

        short_manager = PaperPositionManagerV10(self.config)
        short_manager.open_position("SHORT", 100.0, 1, 100)
        self.assertGreater(short_manager.apply_funding(200, 0.001, 100.0), 0)

    def test_pending_entry_requires_timely_later_event(self):
        pending = PendingEntry("LONG", 1, 10_000)
        self.assertEqual(pending.status(9_999, 5_000), "TOO_EARLY")
        self.assertEqual(pending.status(10_000, 5_000), "TOO_EARLY")
        self.assertEqual(pending.status(10_001, 5_000), "ELIGIBLE")
        self.assertEqual(pending.status(15_001, 5_000), "EXPIRED")


class PaperStoreV10Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "paper.sqlite3"
        self.store = PaperStoreV10(self.database)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    @staticmethod
    def _trade(net_pnl=5.0):
        return {
            "position": "LONG",
            "entry_market": 100.0,
            "entry": 100.01,
            "exit_market": 101.0,
            "exit": 100.9899,
            "quantity": 10.0,
            "reason": "TEST",
            "gross_pnl": 9.799,
            "fees": 0.8,
            "funding_pnl": 0.0,
            "net_pnl": net_pnl,
            "balance_after": 1_000.0 + net_pnl,
            "entry_event_time": 100,
            "exit_event_time": 200,
            "candle_time": 1,
        }

    def test_close_transaction_records_trade_and_clears_position(self):
        self.store.save_position({"position": "LONG", "entry": 100.0})
        self.store.commit_close(self._trade())
        self.assertIsNone(self.store.load_active_position())
        stats = self.store.stats()
        self.assertEqual(stats["trades"], 1)
        self.assertEqual(stats["wins"], 1)
        self.assertTrue(self.store.csv_path.exists())

    def test_zero_pnl_is_not_counted_as_win(self):
        self.store.commit_close(self._trade(net_pnl=0.0))
        stats = self.store.stats()
        self.assertEqual(stats["wins"], 0)
        self.assertEqual(stats["losses"], 1)

    def test_unclean_restart_quarantines_active_position(self):
        payload = {"position": "SHORT", "entry": 100.0}
        self.store.save_position(payload)
        interrupted = self.store.quarantine_interrupted_position()
        self.assertEqual(interrupted, payload)
        self.assertIsNone(self.store.load_active_position())


class MarketDataV10Tests(unittest.TestCase):
    def test_interval_conversion(self):
        self.assertEqual(interval_to_milliseconds("3m"), 180_000)
        self.assertEqual(interval_to_milliseconds("1h"), 3_600_000)

    def test_old_recovered_candle_cannot_enter(self):
        now_ms = 1_000_000
        candle = {
            "time": now_ms - 200_000,
            "close_time": now_ms - 20_000,
            "recovered": True,
        }
        self.assertFalse(candle_entry_is_timely(candle, 5_000, now_ms=now_ms))

    def test_near_live_recovered_candle_can_enter(self):
        now_ms = 1_000_000
        candle = {
            "time": now_ms - 181_000,
            "close_time": now_ms - 1_000,
            "recovered": True,
        }
        self.assertTrue(candle_entry_is_timely(candle, 5_000, now_ms=now_ms))

    def test_live_ws_candle_is_entry_eligible(self):
        self.assertTrue(
            candle_entry_is_timely(
                {"time": 819_000, "close_time": 999_000, "replayed": False},
                5_000,
                now_ms=999_999,
            )
        )

    def test_delayed_ws_candle_cannot_enter(self):
        self.assertFalse(
            candle_entry_is_timely(
                {"time": 1, "close_time": 2, "replayed": False},
                5_000,
                now_ms=999_999,
            )
        )

    def test_current_split_websocket_routes_are_configured(self):
        self.assertIn("/market/stream?streams=", BinanceMarketDataV10.market_stream_base)
        self.assertIn("/public/stream?streams=", BinanceMarketDataV10.public_stream_base)

    def test_rest_trade_freshness_boundary(self):
        self.assertTrue(
            BinanceMarketDataV10._rest_trade_is_execution_fresh(
                995_000, 5_000, now_ms=1_000_000
            )
        )
        self.assertFalse(
            BinanceMarketDataV10._rest_trade_is_execution_fresh(
                994_999, 5_000, now_ms=1_000_000
            )
        )


class MarketDataV10AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.market = BinanceMarketDataV10()
        self.market.running = True
        self.market._candle_lock = asyncio.Lock()
        self.market._trade_lock = asyncio.Lock()

    async def test_recovered_trade_is_deduplicated_and_can_be_diagnostic_only(self):
        trades = []
        prices = []
        self.market.trade_callback = trades.append
        self.market.price_callback = lambda *args: prices.append(args)
        self.market._last_aggregate_trade_id = 100
        row = {"a": 101, "p": "100.5", "q": "2", "m": False, "T": 500}

        first = await self.market._emit_aggregate_trade(
            row,
            "REST_AGGTRADE_REPLAY",
            execution_eligible=False,
        )
        duplicate = await self.market._emit_aggregate_trade(
            row,
            "WS_AGGTRADE",
            execution_eligible=True,
        )

        self.assertTrue(first)
        self.assertFalse(duplicate)
        self.assertEqual(len(trades), 1)
        self.assertFalse(trades[0]["entry_eligible"])
        self.assertEqual(prices, [])
        self.assertEqual(self.market._last_aggregate_trade_id, 101)

    async def test_busy_book_does_not_hide_silent_kline_and_trade_channels(self):
        calls = []
        loop = asyncio.get_running_loop()
        now = loop.time()
        self.market.channel_stale_seconds = 1.0
        self.market.integrity_poll_seconds = 0.0
        self.market._last_kline_frame_monotonic = now - 20.0
        self.market._last_agg_trade_frame_monotonic = now - 20.0
        self.market._last_book_frame_monotonic = now

        async def candle_sync(session):
            calls.append("candle_rest")
            return 0

        async def trade_sync(session):
            calls.append("trade_rest")
            return (0, 0)

        async def book_poll(session):
            calls.append("book_rest")

        async def funding_poll(session):
            calls.append("funding")
            self.market.running = False

        self.market._rest_candle_integrity_sync = candle_sync
        self.market._rest_aggregate_trade_integrity_sync = trade_sync
        self.market._poll_book_ticker = book_poll
        self.market._poll_premium_index = funding_poll

        await self.market._integrity_loop(object())

        self.assertIn("candle_rest", calls)
        self.assertIn("trade_rest", calls)
        self.assertNotIn("book_rest", calls)

    async def test_recent_kline_previews_do_not_hide_missing_completed_bar(self):
        calls = []
        loop = asyncio.get_running_loop()
        now = loop.time()
        self.market.integrity_poll_seconds = 0.0
        self.market._last_kline_frame_monotonic = now
        self.market._last_agg_trade_frame_monotonic = now
        self.market._last_book_frame_monotonic = now
        expected_open = 900_000
        self.market.last_candle_time = expected_open - self.market.interval_ms
        self.market._expected_latest_closed_open_time = lambda: expected_open

        async def candle_sync(session):
            calls.append("candle_rest")
            self.market.last_candle_time = expected_open
            return 1

        async def funding_poll(session):
            calls.append("funding")
            self.market.running = False

        self.market._rest_candle_integrity_sync = candle_sync
        self.market._poll_premium_index = funding_poll

        await self.market._integrity_loop(object())

        self.assertIn("candle_rest", calls)
        self.assertEqual(self.market.last_candle_time, expected_open)

    async def test_missing_candle_recovery_reaches_decision_callback(self):
        now_ms = int(time.time() * 1000)
        prior_open = now_ms - 600_000
        missing_open = prior_open + self.market.interval_ms
        row = [
            missing_open,
            "100",
            "101",
            "99",
            "100.5",
            "10",
            missing_open + self.market.interval_ms - 1,
        ]
        self.market.last_candle_time = prior_open
        decisions = []
        history = []
        self.market.candle_callback = decisions.append
        self.market.history_callback = history.append

        async def fake_fetch(session, *, limit=200, start_time=None):
            return [row]

        self.market._fetch_klines = fake_fetch
        recovered = await self.market._replay_missing(object())

        self.assertEqual(recovered, 1)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(history, [])
        self.assertTrue(decisions[0]["recovered"])
        self.assertEqual(decisions[0]["source"], "REST_KLINE_RECOVERY")


if __name__ == "__main__":
    unittest.main()
