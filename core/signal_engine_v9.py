class SignalEngineV9:
    """V9 EMA trend filter.

    Baseline remains EMA 5 / EMA 13. A direction is tradable only when:
      * fast EMA is on the correct side of slow EMA,
      * EMA separation is meaningful relative to ATR(14),
      * the slow EMA is sloping in the same direction, and
      * the close is on the correct side of the slow EMA.

    Otherwise V9 returns WAIT. This is designed to reduce V8 whipsaw reversals
    without changing the fixed 2R risk/reward model.
    """

    def __init__(
        self,
        fast_period=5,
        slow_period=13,
        atr_period=14,
        slope_lookback=3,
        min_gap_atr=0.10,
    ):
        self.fast_period = int(fast_period)
        self.slow_period = int(slow_period)
        self.atr_period = int(atr_period)
        self.slope_lookback = int(slope_lookback)
        self.min_gap_atr = float(min_gap_atr)

    def calculate_ema(self, prices, period):
        if len(prices) < period:
            return None

        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = ((price - ema) * multiplier) + ema

        return float(ema)

    def calculate_atr(self, candles):
        if len(candles) < self.atr_period + 1:
            return None

        recent = candles[-(self.atr_period + 1):]
        true_ranges = []

        for index in range(1, len(recent)):
            current = recent[index]
            previous = recent[index - 1]

            high = float(current["high"])
            low = float(current["low"])
            previous_close = float(previous["close"])

            true_ranges.append(
                max(
                    high - low,
                    abs(high - previous_close),
                    abs(low - previous_close),
                )
            )

        if not true_ranges:
            return None

        return float(sum(true_ranges) / len(true_ranges))

    def analyze(self, candles):
        minimum = max(
            self.slow_period + self.slope_lookback,
            self.atr_period + 1,
        )

        if len(candles) < minimum:
            return {
                "signal": "WAIT",
                "reason": f"Waiting for candles ({len(candles)}/{minimum})",
                "fast_ema": None,
                "slow_ema": None,
                "atr": None,
                "gap_atr": None,
                "slow_slope": None,
            }

        closes = [float(c["close"]) for c in candles]
        fast_ema = self.calculate_ema(closes, self.fast_period)
        slow_ema = self.calculate_ema(closes, self.slow_period)
        atr = self.calculate_atr(candles)

        previous_closes = closes[:-self.slope_lookback]
        previous_slow = self.calculate_ema(
            previous_closes,
            self.slow_period,
        )

        if None in (fast_ema, slow_ema, atr, previous_slow):
            return {
                "signal": "WAIT",
                "reason": "Indicator calculation unavailable",
                "fast_ema": fast_ema,
                "slow_ema": slow_ema,
                "atr": atr,
                "gap_atr": None,
                "slow_slope": None,
            }

        gap = abs(fast_ema - slow_ema)
        gap_atr = (gap / atr) if atr > 0 else 0.0
        slow_slope = slow_ema - previous_slow
        price = closes[-1]

        if fast_ema > slow_ema:
            if gap_atr < self.min_gap_atr:
                signal = "WAIT"
                reason = (
                    f"EMA LONG rejected: gap too small "
                    f"({gap_atr:.2f} ATR < {self.min_gap_atr:.2f})"
                )
            elif slow_slope <= 0:
                signal = "WAIT"
                reason = "EMA LONG rejected: slow EMA is not rising"
            elif price <= slow_ema:
                signal = "WAIT"
                reason = "EMA LONG rejected: close is not above slow EMA"
            else:
                signal = "LONG"
                reason = "EMA LONG confirmed by ATR gap and rising trend"

        elif fast_ema < slow_ema:
            if gap_atr < self.min_gap_atr:
                signal = "WAIT"
                reason = (
                    f"EMA SHORT rejected: gap too small "
                    f"({gap_atr:.2f} ATR < {self.min_gap_atr:.2f})"
                )
            elif slow_slope >= 0:
                signal = "WAIT"
                reason = "EMA SHORT rejected: slow EMA is not falling"
            elif price >= slow_ema:
                signal = "WAIT"
                reason = "EMA SHORT rejected: close is not below slow EMA"
            else:
                signal = "SHORT"
                reason = "EMA SHORT confirmed by ATR gap and falling trend"
        else:
            signal = "WAIT"
            reason = "EMAs are equal"

        return {
            "signal": signal,
            "reason": reason,
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "atr": atr,
            "gap_atr": gap_atr,
            "slow_slope": slow_slope,
            "price": price,
        }

    def generate_signal(self, candles):
        result = self.analyze(candles)
        return {
            "signal": result["signal"],
            "reason": result["reason"],
            "ema_fast": result["fast_ema"],
            "ema_slow": result["slow_ema"],
            "atr": result.get("atr"),
            "gap_atr": result.get("gap_atr"),
            "slow_slope": result.get("slow_slope"),
            "price": result.get("price"),
        }
