from __future__ import annotations

import json
import math
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_session(event_time_ms: int) -> str:
    hour = datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc).hour
    if 13 <= hour < 16:
        return "LONDON_NEW_YORK"
    if 7 <= hour < 8:
        return "ASIA_LONDON"
    if 0 <= hour < 7:
        return "ASIA"
    if 8 <= hour < 13:
        return "LONDON"
    if 16 <= hour < 22:
        return "NEW_YORK"
    return "OFF_PEAK"


class CausalStructureTracker:
    """Confirms a swing only after `right` completed bars have elapsed."""

    def __init__(self, left: int = 3, right: int = 3) -> None:
        self.left = int(left)
        self.right = int(right)
        self.candles: list[dict[str, Any]] = []
        self.highs: list[dict[str, Any]] = []
        self.lows: list[dict[str, Any]] = []
        self._confirmed_times: set[tuple[str, int]] = set()

    def add_candle(self, candle: dict[str, Any]) -> None:
        if self.candles and int(self.candles[-1]["time"]) == int(candle["time"]):
            self.candles[-1] = dict(candle)
            return
        self.candles.append(dict(candle))
        if len(self.candles) > 500:
            self.candles = self.candles[-500:]

        candidate_index = len(self.candles) - 1 - self.right
        if candidate_index < self.left:
            return
        start = candidate_index - self.left
        end = candidate_index + self.right + 1
        window = self.candles[start:end]
        if len(window) != self.left + self.right + 1:
            return

        candidate = self.candles[candidate_index]
        candidate_time = int(candidate["time"])
        confirmed_at = int(candle.get("close_time", candle["time"]))
        high = float(candidate["high"])
        low = float(candidate["low"])

        if high == max(float(item["high"]) for item in window):
            key = ("HIGH", candidate_time)
            if key not in self._confirmed_times:
                self.highs.append(
                    {
                        "kind": "HIGH",
                        "time": candidate_time,
                        "price": high,
                        "confirmed_at": confirmed_at,
                    }
                )
                self._confirmed_times.add(key)

        if low == min(float(item["low"]) for item in window):
            key = ("LOW", candidate_time)
            if key not in self._confirmed_times:
                self.lows.append(
                    {
                        "kind": "LOW",
                        "time": candidate_time,
                        "price": low,
                        "confirmed_at": confirmed_at,
                    }
                )
                self._confirmed_times.add(key)

        self.highs = self.highs[-100:]
        self.lows = self.lows[-100:]

    def snapshot(self, candle: dict[str, Any]) -> dict[str, Any]:
        close = float(candle["close"])
        latest_high = self.highs[-1] if self.highs else None
        latest_low = self.lows[-1] if self.lows else None
        high_price = float(latest_high["price"]) if latest_high else None
        low_price = float(latest_low["price"]) if latest_low else None
        return {
            "last_swing_high": high_price,
            "last_swing_low": low_price,
            "swing_high_distance_bps": (
                (high_price - close) / close * 10_000 if high_price else None
            ),
            "swing_low_distance_bps": (
                (close - low_price) / close * 10_000 if low_price else None
            ),
            "break_above_swing": bool(high_price is not None and close > high_price),
            "break_below_swing": bool(low_price is not None and close < low_price),
            "bearish_sweep_reclaim": bool(
                high_price is not None
                and float(candle["high"]) > high_price
                and close < high_price
            ),
            "bullish_sweep_reclaim": bool(
                low_price is not None
                and float(candle["low"]) < low_price
                and close > low_price
            ),
        }


class OrderFlowTracker:
    def __init__(self, window_ms: int = 60_000) -> None:
        self.window_ms = int(window_ms)
        self.trades: deque[dict[str, Any]] = deque()
        self.last_source = "NONE"

    def update(self, trade: dict[str, Any]) -> None:
        self.trades.append(dict(trade))
        self.last_source = str(trade.get("source", "UNKNOWN"))
        self._prune(int(trade["event_time"]))

    def _prune(self, as_of_ms: int) -> None:
        cutoff = as_of_ms - self.window_ms
        while self.trades and int(self.trades[0]["event_time"]) < cutoff:
            self.trades.popleft()

    def snapshot(self, as_of_ms: int) -> dict[str, Any]:
        as_of_ms = int(as_of_ms)
        self._prune(as_of_ms)
        cutoff = as_of_ms - self.window_ms
        # Recovery can process a completed candle after newer live trades have
        # already arrived. Never let those future trades leak into that decision.
        visible = [
            item
            for item in self.trades
            if cutoff <= int(item["event_time"]) <= as_of_ms
        ]
        buy_qty = sum(
            float(item["quantity"])
            for item in visible
            if not bool(item["buyer_is_maker"])
        )
        sell_qty = sum(
            float(item["quantity"])
            for item in visible
            if bool(item["buyer_is_maker"])
        )
        total_qty = buy_qty + sell_qty
        turnover = sum(
            float(item["price"]) * float(item["quantity"])
            for item in visible
        )
        last_time = int(visible[-1]["event_time"]) if visible else None
        last_source = str(visible[-1].get("source", "UNKNOWN")) if visible else "NONE"
        return {
            "buy_qty_60s": buy_qty,
            "sell_qty_60s": sell_qty,
            "flow_imbalance_60s": (
                (buy_qty - sell_qty) / total_qty if total_qty > 0 else 0.0
            ),
            "trade_count_60s": len(visible),
            "turnover_60s": turnover,
            "last_trade_event_time": last_time,
            "trade_age_ms": (
                max(0, as_of_ms - last_time) if last_time is not None else None
            ),
            "feed_source": last_source,
        }


class BookQualityTracker:
    def __init__(self, max_events: int = 10_000, max_age_ms: int = 180_000) -> None:
        self.max_events = int(max_events)
        self.max_age_ms = int(max_age_ms)
        self.books: deque[dict[str, Any]] = deque(maxlen=self.max_events)
        self.book: dict[str, Any] | None = None

    def update(self, book: dict[str, Any]) -> None:
        observed = dict(book)
        self.book = observed
        self.books.append(observed)
        newest_time = int(observed["event_time"])
        cutoff = newest_time - self.max_age_ms
        while self.books and int(self.books[0]["event_time"]) < cutoff:
            self.books.popleft()

    def snapshot(self, as_of_ms: int) -> dict[str, Any]:
        # Recovered candles are normally processed just after their close. Keep
        # a bounded history so the last quote at-or-before the decision is used,
        # rather than discarding book diagnostics because the newest quote is a
        # few milliseconds in the future.
        visible = next(
            (
                item
                for item in reversed(self.books)
                if int(item["event_time"]) <= int(as_of_ms)
            ),
            None,
        )
        if visible is None:
            return {
                "bid": None,
                "ask": None,
                "spread_bps": None,
                "book_age_ms": None,
                "book_source": "NONE",
            }
        bid = float(visible["bid"])
        ask = float(visible["ask"])
        midpoint = (bid + ask) / 2.0
        return {
            "bid": bid,
            "ask": ask,
            "bid_quantity": float(visible["bid_quantity"]),
            "ask_quantity": float(visible["ask_quantity"]),
            "spread_bps": ((ask - bid) / midpoint * 10_000) if midpoint > 0 else None,
            "book_age_ms": max(0, int(as_of_ms) - int(visible["event_time"])),
            "book_source": str(visible.get("source", "UNKNOWN")),
        }


def candle_pattern(candles: list[dict[str, Any]]) -> str:
    if not candles:
        return "NONE"
    current = candles[-1]
    open_price = float(current["open"])
    high = float(current["high"])
    low = float(current["low"])
    close = float(current["close"])
    candle_range = max(high - low, 1e-12)
    body = abs(close - open_price)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low

    if body / candle_range <= 0.10:
        return "DOJI"
    if lower_wick >= body * 2.0 and upper_wick <= body:
        return "HAMMER"
    if upper_wick >= body * 2.0 and lower_wick <= body:
        return "SHOOTING_STAR"
    if len(candles) >= 2:
        previous = candles[-2]
        po = float(previous["open"])
        pc = float(previous["close"])
        if close > open_price and pc < po and open_price <= pc and close >= po:
            return "BULLISH_ENGULFING"
        if close < open_price and pc > po and open_price >= pc and close <= po:
            return "BEARISH_ENGULFING"
        if high < float(previous["high"]) and low > float(previous["low"]):
            return "INSIDE_BAR"
        if high > float(previous["high"]) and low < float(previous["low"]):
            return "OUTSIDE_BAR"
    return "NONE"


def market_regime(candles: list[dict[str, Any]]) -> dict[str, Any]:
    if len(candles) < 21:
        return {"regime": "WARMUP", "efficiency20": None, "atr14": None}
    recent = candles[-21:]
    closes = [float(item["close"]) for item in recent]
    movement = sum(abs(closes[index] - closes[index - 1]) for index in range(1, 21))
    efficiency = abs(closes[-1] - closes[0]) / movement if movement > 0 else 0.0

    true_ranges = []
    for index in range(1, len(recent)):
        high = float(recent[index]["high"])
        low = float(recent[index]["low"])
        previous_close = float(recent[index - 1]["close"])
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr14 = sum(true_ranges[-14:]) / 14.0
    current_range = float(recent[-1]["high"]) - float(recent[-1]["low"])

    def ema(values: list[float], period: int) -> float:
        alpha = 2.0 / (period + 1.0)
        value = values[0]
        for item in values[1:]:
            value = alpha * item + (1.0 - alpha) * value
        return value

    fast = ema(closes, 5)
    slow = ema(closes, 13)
    if atr14 > 0 and current_range >= 2.5 * atr14:
        regime = "SHOCK"
    elif efficiency >= 0.25 and fast > slow:
        regime = "TREND_UP"
    elif efficiency >= 0.25 and fast < slow:
        regime = "TREND_DOWN"
    elif efficiency <= 0.15:
        regime = "RANGE"
    else:
        regime = "TRANSITION"
    return {
        "regime": regime,
        "efficiency20": efficiency,
        "atr14": atr14,
        "atr_pct": atr14 / closes[-1] * 100.0 if closes[-1] else None,
    }


class StrategyHealthTracker:
    def __init__(self, prior_net_pnls: list[float] | None = None) -> None:
        self.net_pnls = list(prior_net_pnls or [])[-20:]

    def update(self, net_pnl: float) -> None:
        self.net_pnls.append(float(net_pnl))
        self.net_pnls = self.net_pnls[-20:]

    def state(self) -> str:
        if len(self.net_pnls) < 10:
            return "WARMUP"
        last10 = self.net_pnls[-10:]
        mean10 = sum(last10) / len(last10)
        if mean10 > 0:
            return "HEALTHY"
        if len(self.net_pnls) >= 20 and sum(self.net_pnls) / 20.0 > 0:
            return "DEGRADING"
        return "BROKEN_DIAGNOSTIC"


class TradePathTracker:
    def __init__(self) -> None:
        self.active: dict[str, Any] | None = None

    def start(self, position: dict[str, Any]) -> None:
        self.active = {
            "side": position["position"],
            "entry": float(position["entry"]),
            "stop": float(position["stop_loss"]),
            "entry_time": int(position["entry_event_time"]),
            "mfe_r": 0.0,
            "mae_r": 0.0,
            "mfe_time_ms": 0,
            "mae_time_ms": 0,
            "observations": 0,
        }

    def observe(self, price: float, event_time_ms: int) -> None:
        if self.active is None:
            return
        side = self.active["side"]
        entry = float(self.active["entry"])
        risk_distance = abs(entry - float(self.active["stop"]))
        if risk_distance <= 0:
            return
        signed = float(price) - entry if side == "LONG" else entry - float(price)
        favorable_r = max(0.0, signed / risk_distance)
        adverse_r = max(0.0, -signed / risk_distance)
        elapsed = max(0, int(event_time_ms) - int(self.active["entry_time"]))
        if favorable_r > float(self.active["mfe_r"]):
            self.active["mfe_r"] = favorable_r
            self.active["mfe_time_ms"] = elapsed
        if adverse_r > float(self.active["mae_r"]):
            self.active["mae_r"] = adverse_r
            self.active["mae_time_ms"] = elapsed
        self.active["observations"] = int(self.active["observations"]) + 1

    def finish(self) -> dict[str, Any]:
        result = dict(self.active or {})
        self.active = None
        return result


class DiagnosticStoreV10_1:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        # Constructed by Qt, then used by the dedicated asyncio worker.
        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    candle_time INTEGER NOT NULL,
                    decision_time INTEGER NOT NULL,
                    signal TEXT NOT NULL,
                    safety_gate TEXT NOT NULL,
                    features_json TEXT NOT NULL
                )
                """
            )

    def record_decision(
        self,
        candle_time: int,
        decision_time: int,
        signal: str,
        safety_gate: str,
        features: dict[str, Any],
    ) -> None:
        recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO decisions(
                    recorded_at, candle_time, decision_time, signal,
                    safety_gate, features_json
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    recorded_at,
                    int(candle_time),
                    int(decision_time),
                    str(signal),
                    str(safety_gate),
                    json.dumps(features, sort_keys=True, allow_nan=False),
                ),
            )

    def close(self) -> None:
        self.connection.close()


def finite_or_none(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
