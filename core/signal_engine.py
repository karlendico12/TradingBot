class SignalEngine:

    def __init__(self, fast_period=5, slow_period=13):
        self.fast_period = fast_period
        self.slow_period = slow_period

    def calculate_ema(self, prices, period):

        if len(prices) < period:
            return None

        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = ((price - ema) * multiplier) + ema

        return ema

    # Existing method (kept for compatibility)
    def analyze(self, candles):

        if len(candles) < self.slow_period:
            return {
                "signal": "WAIT",
                "reason": f"Waiting for candles ({len(candles)}/{self.slow_period})",
                "fast_ema": None,
                "slow_ema": None,
            }

        prices = [float(c["close"]) for c in candles]

        fast_ema = self.calculate_ema(prices, self.fast_period)
        slow_ema = self.calculate_ema(prices, self.slow_period)

        if fast_ema is None or slow_ema is None:
            return {
                "signal": "WAIT",
                "reason": "EMA calculation unavailable",
                "fast_ema": fast_ema,
                "slow_ema": slow_ema,
            }

        if fast_ema > slow_ema:
            signal = "LONG"
            reason = "Fast EMA is above Slow EMA"
        elif fast_ema < slow_ema:
            signal = "SHORT"
            reason = "Fast EMA is below Slow EMA"
        else:
            signal = "WAIT"
            reason = "EMAs are equal"

        return {
            "signal": signal,
            "reason": reason,
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "price": prices[-1],
        }

    # V8 compatibility
    def generate_signal(self, candles):

        result = self.analyze(candles)

        return {
            "signal": result["signal"],
            "reason": result["reason"],
            "ema_fast": result["fast_ema"],
            "ema_slow": result["slow_ema"],
            "price": result.get("price"),
        }