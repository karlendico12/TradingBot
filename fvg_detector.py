class FVGDetector:
    def __init__(self):
        self.active = []

    def update(self, candles):
        if len(candles) < 3:
            return []

        self.active = []

        for i in range(2, len(candles)):
            c1 = candles[i - 2]
            c2 = candles[i - 1]
            c3 = candles[i]

            # Bullish FVG
            if c1["high"] < c3["low"]:
                self.active.append({
                    "type": "bullish",
                    "top": c3["low"],
                    "bottom": c1["high"],
                    "index": i
                })

            # Bearish FVG
            elif c1["low"] > c3["high"]:
                self.active.append({
                    "type": "bearish",
                    "top": c1["low"],
                    "bottom": c3["high"],
                    "index": i
                })

        return self.active