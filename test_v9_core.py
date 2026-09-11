import unittest

from core.signal_engine_v9 import SignalEngineV9


def make_candles(closes, wick=0.8):
    candles = []
    previous = closes[0]
    for i, close in enumerate(closes):
        open_price = previous
        high = max(open_price, close) + wick
        low = min(open_price, close) - wick
        candles.append({
            "time": i,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100.0,
            "closed": True,
        })
        previous = close
    return candles


class SignalEngineV9Tests(unittest.TestCase):
    def test_uptrend_confirms_long(self):
        closes = [100 + i * 0.7 for i in range(40)]
        result = SignalEngineV9().generate_signal(make_candles(closes))
        self.assertEqual(result["signal"], "LONG")

    def test_downtrend_confirms_short(self):
        closes = [130 - i * 0.7 for i in range(40)]
        result = SignalEngineV9().generate_signal(make_candles(closes))
        self.assertEqual(result["signal"], "SHORT")

    def test_tight_chop_waits(self):
        closes = [100 + (0.05 if i % 2 == 0 else -0.05) for i in range(40)]
        result = SignalEngineV9().generate_signal(make_candles(closes, wick=1.0))
        self.assertEqual(result["signal"], "WAIT")

    def test_wait_reason_is_explained(self):
        closes = [100 + (0.05 if i % 2 == 0 else -0.05) for i in range(40)]
        result = SignalEngineV9().generate_signal(make_candles(closes, wick=1.0))
        self.assertTrue(result["reason"])
        self.assertIn("rejected", result["reason"].lower())


if __name__ == "__main__":
    unittest.main()
