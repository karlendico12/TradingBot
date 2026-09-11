class OrderBlockDetector:
    def __init__(self):
        self.blocks = []

    def update(self, candles):
        if len(candles) < 5:
            return []

        self.blocks = []

        for i in range(2, len(candles) - 1):
            c = candles[i]
            nxt = candles[i + 1]

            body = abs(c["close"] - c["open"])
            next_body = abs(nxt["close"] - nxt["open"])

            # Bullish Order Block
            if (
                c["close"] < c["open"]
                and nxt["close"] > nxt["open"]
                and next_body > body * 1.5
            ):
                self.blocks.append({
                    "type": "bullish",
                    "top": c["open"],
                    "bottom": c["low"],
                    "index": i
                })

            # Bearish Order Block
            elif (
                c["close"] > c["open"]
                and nxt["close"] < nxt["open"]
                and next_body > body * 1.5
            ):
                self.blocks.append({
                    "type": "bearish",
                    "top": c["high"],
                    "bottom": c["open"],
                    "index": i
                })

        return self.blocks