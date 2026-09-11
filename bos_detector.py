class BOSDetector:
    def __init__(self):
        self.last_bos = None

    def check(self, candles, swing_highs, swing_lows):
        if len(candles) < 2:
            return None

        current_close = candles[-1]["close"]

        # Bullish BOS
        if swing_highs:
            last_high = swing_highs[-1][1]

            if current_close > last_high and self.last_bos != ("bull", last_high):
                self.last_bos = ("bull", last_high)
                return {
                    "type": "bullish",
                    "level": last_high,
                    "price": current_close
                }

        # Bearish BOS
        if swing_lows:
            last_low = swing_lows[-1][1]

            if current_close < last_low and self.last_bos != ("bear", last_low):
                self.last_bos = ("bear", last_low)
                return {
                    "type": "bearish",
                    "level": last_low,
                    "price": current_close
                }

        return None