import json
import tempfile
import unittest
from pathlib import Path

from core.diagnostics_v10_1 import (
    BookQualityTracker,
    CausalStructureTracker,
    DiagnosticStoreV10_1,
    OrderFlowTracker,
    StrategyHealthTracker,
    TradePathTracker,
    candle_pattern,
    market_regime,
    utc_session,
)


def candle(index, open_price, high, low, close):
    return {
        "time": index * 180_000,
        "close_time": index * 180_000 + 179_999,
        "open": float(open_price),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": 100.0,
        "closed": True,
    }


class StructureTests(unittest.TestCase):
    def test_swing_requires_three_right_hand_candles(self):
        tracker = CausalStructureTracker(left=3, right=3)
        candles = [
            candle(0, 100, 101, 99, 100),
            candle(1, 100, 102, 99, 101),
            candle(2, 101, 103, 100, 102),
            candle(3, 102, 110, 101, 103),
            candle(4, 103, 104, 100, 102),
            candle(5, 102, 103, 99, 101),
            candle(6, 101, 102, 98, 100),
        ]
        for item in candles[:6]:
            tracker.add_candle(item)
        self.assertEqual(tracker.highs, [])
        tracker.add_candle(candles[6])
        self.assertEqual(len(tracker.highs), 1)
        self.assertEqual(tracker.highs[0]["time"], candles[3]["time"])
        self.assertEqual(tracker.highs[0]["confirmed_at"], candles[6]["close_time"])


class FlowAndBookTests(unittest.TestCase):
    def test_order_flow_imbalance_uses_aggressor_side(self):
        tracker = OrderFlowTracker(window_ms=60_000)
        tracker.update(
            {
                "event_time": 100_000,
                "price": 100,
                "quantity": 3,
                "buyer_is_maker": False,
                "source": "TEST",
            }
        )
        tracker.update(
            {
                "event_time": 110_000,
                "price": 100,
                "quantity": 1,
                "buyer_is_maker": True,
                "source": "TEST",
            }
        )
        snapshot = tracker.snapshot(110_000)
        self.assertAlmostEqual(snapshot["flow_imbalance_60s"], 0.5)
        self.assertEqual(snapshot["trade_count_60s"], 2)

    def test_old_flow_is_pruned(self):
        tracker = OrderFlowTracker(window_ms=60_000)
        tracker.update(
            {
                "event_time": 1,
                "price": 100,
                "quantity": 1,
                "buyer_is_maker": False,
            }
        )
        self.assertEqual(tracker.snapshot(60_002)["trade_count_60s"], 0)

    def test_future_trade_is_excluded_from_recovered_snapshot(self):
        tracker = OrderFlowTracker(window_ms=60_000)
        tracker.update(
            {
                "event_time": 100_000,
                "price": 100,
                "quantity": 2,
                "buyer_is_maker": False,
                "source": "BEFORE",
            }
        )
        tracker.update(
            {
                "event_time": 110_000,
                "price": 101,
                "quantity": 9,
                "buyer_is_maker": True,
                "source": "FUTURE",
            }
        )
        snapshot = tracker.snapshot(105_000)
        self.assertEqual(snapshot["trade_count_60s"], 1)
        self.assertEqual(snapshot["feed_source"], "BEFORE")
        self.assertEqual(snapshot["last_trade_event_time"], 100_000)

    def test_book_spread_is_reported_in_bps(self):
        tracker = BookQualityTracker()
        tracker.update(
            {
                "bid": 99.9,
                "ask": 100.1,
                "bid_quantity": 2,
                "ask_quantity": 3,
                "event_time": 1_000,
                "source": "TEST",
            }
        )
        self.assertAlmostEqual(tracker.snapshot(1_100)["spread_bps"], 20.0)

    def test_future_book_is_not_used_for_recovered_snapshot(self):
        tracker = BookQualityTracker()
        tracker.update(
            {
                "bid": 99.9,
                "ask": 100.1,
                "bid_quantity": 2,
                "ask_quantity": 3,
                "event_time": 2_000,
                "source": "FUTURE_BOOK",
            }
        )
        snapshot = tracker.snapshot(1_500)
        self.assertIsNone(snapshot["spread_bps"])
        self.assertEqual(snapshot["book_source"], "NONE")

    def test_book_history_uses_latest_quote_at_or_before_decision(self):
        tracker = BookQualityTracker()
        tracker.update(
            {
                "bid": 99.9,
                "ask": 100.1,
                "bid_quantity": 2,
                "ask_quantity": 3,
                "event_time": 1_000,
                "source": "BEFORE",
            }
        )
        tracker.update(
            {
                "bid": 100.9,
                "ask": 101.1,
                "bid_quantity": 4,
                "ask_quantity": 5,
                "event_time": 2_000,
                "source": "AFTER",
            }
        )
        snapshot = tracker.snapshot(1_500)
        self.assertEqual(snapshot["book_source"], "BEFORE")
        self.assertEqual(snapshot["bid"], 99.9)
        self.assertEqual(snapshot["ask"], 100.1)


class PatternRegimeAndPathTests(unittest.TestCase):
    def test_bullish_engulfing_pattern(self):
        candles = [
            candle(0, 101, 102, 98, 99),
            candle(1, 98.5, 102, 98, 101.5),
        ]
        self.assertEqual(candle_pattern(candles), "BULLISH_ENGULFING")

    def test_trending_prices_get_trend_regime(self):
        candles = [
            candle(i, 100 + i, 101.2 + i, 99.8 + i, 101 + i)
            for i in range(25)
        ]
        self.assertEqual(market_regime(candles)["regime"], "TREND_UP")

    def test_trade_path_tracks_mfe_and_mae_causally(self):
        tracker = TradePathTracker()
        tracker.start(
            {
                "position": "LONG",
                "entry": 100.0,
                "stop_loss": 99.0,
                "entry_event_time": 1_000,
            }
        )
        tracker.observe(102.0, 2_000)
        tracker.observe(99.5, 3_000)
        result = tracker.finish()
        self.assertAlmostEqual(result["mfe_r"], 2.0)
        self.assertAlmostEqual(result["mae_r"], 0.5)
        self.assertEqual(result["observations"], 2)

    def test_strategy_health_is_diagnostic(self):
        tracker = StrategyHealthTracker([1.0] * 10)
        self.assertEqual(tracker.state(), "HEALTHY")
        tracker = StrategyHealthTracker([-1.0] * 20)
        self.assertEqual(tracker.state(), "BROKEN_DIAGNOSTIC")

    def test_session_is_deterministic(self):
        self.assertEqual(utc_session(14 * 3_600_000), "LONDON_NEW_YORK")


class DiagnosticStoreTests(unittest.TestCase):
    def test_decision_snapshot_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics.sqlite3"
            store = DiagnosticStoreV10_1(path)
            store.record_decision(1, 2, "LONG", "PASS", {"regime": "TREND_UP"})
            row = store.connection.execute(
                "SELECT signal, safety_gate, features_json FROM decisions"
            ).fetchone()
            self.assertEqual(row[0], "LONG")
            self.assertEqual(row[1], "PASS")
            self.assertEqual(json.loads(row[2])["regime"], "TREND_UP")
            store.close()


if __name__ == "__main__":
    unittest.main()
