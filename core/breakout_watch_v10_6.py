from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BreakoutWatchConfigV10_6:
    lifetime_ms: int = 180_000
    break_buffer_bps: float = 2.0
    reclaim_buffer_bps: float = 1.0
    confirmation_ms: int = 1_000
    minimum_trade_count_60s: int = 20
    minimum_abs_flow_imbalance: float = 0.05

    def __post_init__(self) -> None:
        if self.lifetime_ms <= 0:
            raise ValueError("lifetime_ms must be positive")
        if self.break_buffer_bps <= 0:
            raise ValueError("break_buffer_bps must be positive")
        if self.reclaim_buffer_bps < 0:
            raise ValueError("reclaim_buffer_bps cannot be negative")
        if self.confirmation_ms <= 0:
            raise ValueError("confirmation_ms must be positive")
        if self.minimum_trade_count_60s <= 0:
            raise ValueError("minimum_trade_count_60s must be positive")
        if not 0 < self.minimum_abs_flow_imbalance < 1:
            raise ValueError("minimum_abs_flow_imbalance must be between zero and one")


@dataclass(frozen=True)
class BreakoutObservationV10_6:
    status: str
    reason: str
    trigger: bool = False
    cancel: bool = False


@dataclass
class BreakoutWatchStateV10_6:
    side: str
    level: float
    candle_time: int
    decision_time: int
    armed_time: int
    expiry_time: int
    atr14: float | None
    opposing_levels: tuple[float, ...]
    first_break_time: int | None = None
    observations: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class BreakoutWatchV10_6:
    """Causal raw-trade confirmation after a structurally cramped entry.

    A completed 3m decision must arm the watch. Raw trades can then authorize
    an entry only after price remains beyond the level for the configured
    confirmation time and contemporaneous 60s aggressor flow agrees.
    """

    def __init__(self, config: BreakoutWatchConfigV10_6 | None = None) -> None:
        self.config = config or BreakoutWatchConfigV10_6()
        self.state: BreakoutWatchStateV10_6 | None = None

    def arm(
        self,
        *,
        side: str,
        level: float,
        candle_time: int,
        decision_time: int,
        armed_time: int,
        atr14: float | None,
        opposing_levels: tuple[float, ...],
    ) -> BreakoutWatchStateV10_6:
        side = str(side).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError(f"invalid side: {side}")
        level = float(level)
        if level <= 0:
            raise ValueError("level must be positive")
        self.state = BreakoutWatchStateV10_6(
            side=side,
            level=level,
            candle_time=int(candle_time),
            decision_time=int(decision_time),
            armed_time=int(armed_time),
            expiry_time=int(decision_time) + self.config.lifetime_ms,
            atr14=None if atr14 is None else float(atr14),
            opposing_levels=tuple(float(item) for item in opposing_levels),
        )
        return self.state

    def cancel(self) -> BreakoutWatchStateV10_6 | None:
        prior = self.state
        self.state = None
        return prior

    def snapshot(self) -> dict[str, Any]:
        return {
            "config": asdict(self.config),
            "state": None if self.state is None else self.state.as_dict(),
        }

    def observe(
        self,
        *,
        price: float,
        event_time: int,
        trade_count_60s: int,
        flow_imbalance_60s: float,
    ) -> BreakoutObservationV10_6:
        state = self.state
        if state is None:
            return BreakoutObservationV10_6("IDLE", "NO_WATCH")
        event_time = int(event_time)
        price = float(price)
        if event_time <= state.armed_time:
            return BreakoutObservationV10_6("WAIT", "PRE_ARM_TRADE")
        if event_time > state.expiry_time:
            return BreakoutObservationV10_6("CANCEL", "EXPIRED", cancel=True)

        state.observations += 1
        break_fraction = self.config.break_buffer_bps / 10_000.0
        reclaim_fraction = self.config.reclaim_buffer_bps / 10_000.0
        threshold = (
            state.level * (1.0 + break_fraction)
            if state.side == "LONG"
            else state.level * (1.0 - break_fraction)
        )
        beyond = price >= threshold if state.side == "LONG" else price <= threshold

        if state.first_break_time is not None:
            reclaim = (
                price < state.level * (1.0 - reclaim_fraction)
                if state.side == "LONG"
                else price > state.level * (1.0 + reclaim_fraction)
            )
            if reclaim:
                return BreakoutObservationV10_6(
                    "CANCEL", "LEVEL_RECLAIMED", cancel=True
                )
        if not beyond:
            return BreakoutObservationV10_6("WAIT", "LEVEL_NOT_BROKEN")
        if state.first_break_time is None:
            state.first_break_time = event_time
            return BreakoutObservationV10_6("CONFIRMING", "FIRST_TRADE_THROUGH")
        if event_time - state.first_break_time < self.config.confirmation_ms:
            return BreakoutObservationV10_6("CONFIRMING", "HOLD_TIME")

        count_ok = int(trade_count_60s) >= self.config.minimum_trade_count_60s
        imbalance = float(flow_imbalance_60s)
        flow_ok = (
            imbalance >= self.config.minimum_abs_flow_imbalance
            if state.side == "LONG"
            else imbalance <= -self.config.minimum_abs_flow_imbalance
        )
        if not count_ok:
            return BreakoutObservationV10_6("WAIT", "INSUFFICIENT_FLOW_TRADES")
        if not flow_ok:
            return BreakoutObservationV10_6("WAIT", "FLOW_NOT_ALIGNED")
        return BreakoutObservationV10_6("TRIGGER", "CONFIRMED_BREAKOUT", trigger=True)
