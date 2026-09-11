import unittest

from core.significant_structure_v10_8 import SignificantStructureSelectorV10_8


def candles():
    output = []
    for index in range(20):
        output.append(
            {
                "time": index * 180_000,
                "close_time": (index + 1) * 180_000 - 1,
                "open": 100.0,
                "high": 100.2,
                "low": 99.8,
                "close": 100.0,
            }
        )
    return output


class SignificantStructureV10_8Tests(unittest.TestCase):
    def test_isolated_minor_pivot_is_rejected(self):
        data = candles()
        data[10]["high"] = 100.25
        points = [{"time": data[10]["time"], "price": 100.25, "confirmed_at": data[13]["close_time"]}]
        selector = SignificantStructureSelectorV10_8()
        levels = selector.select(
            side="LONG", candles=data, points=points,
            decision_time=data[-1]["close_time"], atr14=1.0,
        )
        self.assertEqual(levels, ())
        self.assertEqual(selector.last_diagnostics[0]["accepted_by"], "REJECTED_MINOR")

    def test_prominent_single_pivot_is_retained(self):
        data = candles()
        data[10]["high"] = 101.0
        points = [{"time": data[10]["time"], "price": 101.0, "confirmed_at": data[13]["close_time"]}]
        selector = SignificantStructureSelectorV10_8()
        levels = selector.select(
            side="LONG", candles=data, points=points,
            decision_time=data[-1]["close_time"], atr14=1.0,
        )
        self.assertEqual(levels, (101.0,))

    def test_repeated_nearby_pivots_form_level(self):
        data = candles()
        points = [
            {"time": data[8]["time"], "price": 100.25, "confirmed_at": data[11]["close_time"]},
            {"time": data[14]["time"], "price": 100.26, "confirmed_at": data[17]["close_time"]},
        ]
        selector = SignificantStructureSelectorV10_8()
        levels = selector.select(
            side="LONG", candles=data, points=points,
            decision_time=data[-1]["close_time"], atr14=1.0,
        )
        self.assertEqual(len(levels), 1)
        self.assertAlmostEqual(levels[0], 100.255)

    def test_short_prominence_is_symmetric(self):
        data = candles()
        data[10]["low"] = 99.0
        points = [{"time": data[10]["time"], "price": 99.0, "confirmed_at": data[13]["close_time"]}]
        selector = SignificantStructureSelectorV10_8()
        levels = selector.select(
            side="SHORT", candles=data, points=points,
            decision_time=data[-1]["close_time"], atr14=1.0,
        )
        self.assertEqual(levels, (99.0,))


if __name__ == "__main__":
    unittest.main()
