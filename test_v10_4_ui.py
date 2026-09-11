import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from terminal_v10_4 import TradingWindowV10_4


class TradingWindowV10_4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = TradingWindowV10_4()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_dashboard_prioritizes_chart_and_tabs(self):
        self.assertEqual(self.window.layout.count(), 3)
        self.assertEqual(self.window.main_splitter.count(), 2)
        self.assertEqual(self.window.side_tabs.count(), 4)
        self.assertGreaterEqual(self.window.chart.minimumHeight(), 520)
        self.assertGreaterEqual(self.window.minimumWidth(), 1200)
        self.assertGreaterEqual(self.window.side_tabs.minimumWidth(), 470)

    def test_profit_guard_and_pnl_are_visually_stateful(self):
        self.window.update_profit_guard(
            {
                "entry_event_time": 1,
                "side": "LONG",
                "armed": True,
                "last_net_r": 0.7,
                "peak_net_r": 0.9,
                "floor_net_r": 0.5,
            }
        )
        self.assertIn("ARMED LONG", self.window.profit_guard_label.text())
        self.assertIn("38d996", self.window.profit_guard_label.styleSheet())

        self.window.update_current_pnl(-2.0)
        self.assertIn("ff6b6b", self.window.current_pnl_label.styleSheet())
        self.window.update_current_pnl(2.0)
        self.assertIn("38d996", self.window.current_pnl_label.styleSheet())

    def test_chart_navigation_buttons_have_safe_empty_state(self):
        self.window.last_candles = []
        self.window._show_latest(60)
        self.window._follow_live()
        self.window._reset_y()
        self.assertFalse(self.window.chart_user_navigated)


if __name__ == "__main__":
    unittest.main()
