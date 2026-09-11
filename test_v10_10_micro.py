import unittest
import os

from core.micro_decision_v10_10 import (
    AggregateTradeOneMinuteBarsV10_10,
    OneMinuteSignalEngineV10_10,
    context_requirement,
)


class AggregateTradeOneMinuteBarsTests(unittest.TestCase):
    def test_closes_bar_only_after_next_minute_trade(self):
        bars = AggregateTradeOneMinuteBarsV10_10()
        self.assertEqual(
            bars.update({"event_time": 60_100, "price": 100.0, "quantity": 2.0}),
            [],
        )
        bars.update({"event_time": 61_000, "price": 101.0, "quantity": 1.0})
        closed = bars.update(
            {"event_time": 120_050, "price": 99.0, "quantity": 3.0}
        )
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["time"], 60_000)
        self.assertEqual(closed[0]["close_time"], 119_999)
        self.assertEqual(closed[0]["high"], 101.0)
        self.assertEqual(closed[0]["close"], 101.0)
        self.assertTrue(closed[0]["closed"])

    def test_old_replayed_trade_does_not_change_current_bar(self):
        bars = AggregateTradeOneMinuteBarsV10_10()
        bars.update({"event_time": 120_100, "price": 100.0})
        bars.update({"event_time": 60_100, "price": 999.0})
        self.assertEqual(bars.current["close"], 100.0)

    def test_seed_is_sorted_and_bounded(self):
        bars = AggregateTradeOneMinuteBarsV10_10(maximum_bars=2)
        bars.seed([
            {"time": 120_000, "close": 2},
            {"time": 0, "close": 0},
            {"time": 60_000, "close": 1},
        ])
        self.assertEqual([x["time"] for x in bars.candles()], [60_000, 120_000])


class OneMinuteSignalTests(unittest.TestCase):
    @staticmethod
    def candles(direction=1):
        result = []
        price = 100.0
        for index in range(30):
            previous = price
            price += direction * 0.20
            result.append({
                "time": index * 60_000,
                "close_time": index * 60_000 + 59_999,
                "open": previous,
                "high": max(previous, price) + 0.05,
                "low": min(previous, price) - 0.05,
                "close": price,
            })
        return result

    def test_uptrend_produces_long(self):
        decision = OneMinuteSignalEngineV10_10().analyze(self.candles(1))
        self.assertEqual(decision.signal, "LONG")

    def test_downtrend_produces_short(self):
        decision = OneMinuteSignalEngineV10_10().analyze(self.candles(-1))
        self.assertEqual(decision.signal, "SHORT")


class ContextRequirementTests(unittest.TestCase):
    def test_aligned_trend_uses_first_signal(self):
        self.assertEqual(context_requirement("SHORT", "TREND_DOWN")[:2], (1, 0.05))

    def test_countertrend_requires_two_and_stronger_flow(self):
        self.assertEqual(context_requirement("LONG", "TREND_DOWN")[:2], (2, 0.15))

    def test_transition_is_not_blocked(self):
        self.assertEqual(context_requirement("LONG", "TRANSITION")[:2], (1, 0.08))


class V10_10WindowLabelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_labels_identify_one_minute_decision_and_three_minute_context(self):
        from PyQt6.QtWidgets import QLabel
        from terminal_v10_10 import TradingWindowV10_10

        window = TradingWindowV10_10()
        try:
            self.assertEqual(window.signal_label.text(), "Closed 1m Signal: WAIT")
            labels = [label.text() for label in window.findChildren(QLabel)]
            self.assertIn(
                "XAUUSDT · 3m context chart · entries use completed 1m",
                labels,
            )
            self.assertIn("loading completed 1m history", window.policy_label.text())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
