from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.signal_engine_v9 import SignalEngineV9


ONE_MINUTE_MS = 60_000


class AggregateTradeOneMinuteBarsV10_10:
    """Build genuine completed 1m OHLCV bars from observed aggregate trades."""

    def __init__(self, maximum_bars: int = 500) -> None:
        self.maximum_bars = int(maximum_bars)
        self.completed: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None

    @staticmethod
    def _bucket(event_time: int) -> int:
        return (int(event_time) // ONE_MINUTE_MS) * ONE_MINUTE_MS

    def seed(self, candles: list[dict[str, Any]]) -> None:
        by_time = {int(item["time"]): dict(item) for item in candles}
        self.completed = [by_time[key] for key in sorted(by_time)][-self.maximum_bars :]

    def _new_bar(self, bucket: int, price: float, quantity: float) -> dict[str, Any]:
        return {
            "time": int(bucket),
            "close_time": int(bucket + ONE_MINUTE_MS - 1),
            "open": float(price),
            "high": float(price),
            "low": float(price),
            "close": float(price),
            "volume": max(0.0, float(quantity)),
            "trade_count": 1,
            "closed": False,
            "source": "AGGTRADE_1M",
        }

    def update(self, trade: dict[str, Any]) -> list[dict[str, Any]]:
        event_time = int(trade["event_time"])
        price = float(trade["price"])
        quantity = float(trade.get("quantity") or trade.get("qty") or 0.0)
        bucket = self._bucket(event_time)
        if self.current is None:
            self.current = self._new_bar(bucket, price, quantity)
            return []
        current_time = int(self.current["time"])
        if bucket < current_time:
            return []
        if bucket == current_time:
            self.current["high"] = max(float(self.current["high"]), price)
            self.current["low"] = min(float(self.current["low"]), price)
            self.current["close"] = price
            self.current["volume"] = float(self.current["volume"]) + max(0.0, quantity)
            self.current["trade_count"] = int(self.current["trade_count"]) + 1
            return []

        closed = dict(self.current)
        closed["closed"] = True
        self.completed.append(closed)
        self.completed = self.completed[-self.maximum_bars :]
        self.current = self._new_bar(bucket, price, quantity)
        return [closed]

    def candles(self) -> list[dict[str, Any]]:
        return list(self.completed)


@dataclass(frozen=True)
class MicroDecisionV10_10:
    signal: str
    reason: str
    fast_ema: float | None
    slow_ema: float | None
    atr14: float | None
    gap_atr: float | None
    slow_slope: float | None


class OneMinuteSignalEngineV10_10:
    """A faster EMA decision engine evaluated only on completed 1m bars."""

    def __init__(self) -> None:
        self.engine = SignalEngineV9(
            fast_period=5,
            slow_period=13,
            atr_period=14,
            slope_lookback=2,
            min_gap_atr=0.06,
        )

    def analyze(self, candles: list[dict[str, Any]]) -> MicroDecisionV10_10:
        result = self.engine.analyze(candles)
        return MicroDecisionV10_10(
            signal=str(result.get("signal", "WAIT")),
            reason=str(result.get("reason", "")),
            fast_ema=result.get("fast_ema"),
            slow_ema=result.get("slow_ema"),
            atr14=result.get("atr"),
            gap_atr=result.get("gap_atr"),
            slow_slope=result.get("slow_slope"),
        )


def context_requirement(side: str, regime: str) -> tuple[int, float, str]:
    """Return required 1m streak and flow for the current 3m context."""
    side = str(side).upper()
    regime = str(regime or "UNKNOWN").upper()
    aligned = (side == "LONG" and regime == "TREND_UP") or (
        side == "SHORT" and regime == "TREND_DOWN"
    )
    opposing = (side == "LONG" and regime == "TREND_DOWN") or (
        side == "SHORT" and regime == "TREND_UP"
    )
    if aligned:
        return 1, 0.05, "ALIGNED_3M_TREND"
    if opposing:
        return 2, 0.15, "COUNTER_3M_TREND"
    return 1, 0.08, f"{regime}_CONTEXT"
