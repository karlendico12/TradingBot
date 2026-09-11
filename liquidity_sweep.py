class LiquiditySweepDetector:
    def __init__(self):
        self.last_signal = None

    def check(self, candles, swing_highs, swing_lows):
        if len(candles) < 2:
            return None

        current = candles[-1]

        # Bullish liquidity sweep
        if swing_highs:
            level = swing_highs[-1][1]

            if current["high"] > level and current["close"] < level:
                signal = ("SELL", level)

                if signal != self.last_signal:
                    self.last_signal = signal
                    return {
                        "side": "SELL",
                        "level": level,
                        "price": current["close"]
                    }

        # Bearish liquidity sweep
        if swing_lows:
            level = swing_lows[-1][1]

            if current["low"] < level and current["close"] > level:
                signal = ("BUY", level)

                if signal != self.last_signal:
                    self.last_signal = signal
                    return {
                        "side": "BUY",
                        "level": level,
                        "price": current["close"]
                    }

        return None