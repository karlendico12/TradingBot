from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FlowAlignmentWatchConfigV10_7:
    lifetime_ms: int = 180_000
    confirmation_ms: int = 1_000
    minimum_trade_count_60s: int = 20
    minimum_abs_flow_imbalance: float = 0.05
    maximum_chase_bps: float = 20.0

    def __post_init__(self) -> None:
        if self.lifetime_ms <= 0 or self.confirmation_ms <= 0:
            raise ValueError("watch and confirmation durations must be positive")
        if self.minimum_trade_count_60s <= 0:
            raise ValueError("minimum trade count must be positive")
        if not 0 < self.minimum_abs_flow_imbalance < 1:
            raise ValueError("flow threshold must be between zero and one")
        if self.maximum_chase_bps <= 0:
            raise ValueError("maximum_chase_bps must be positive")


@dataclass
class FlowAlignmentWatchStateV10_7:
    side: str
    candle_time: int
    decision_time: int
    decision_price: float
    expiry_time: int
    atr14: float | None
    opposing_levels: tuple[float, ...]
    first_aligned_time: int | None = None
    observations: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FlowAlignmentObservationV10_7:
    status: str
    reason: str
    trigger: bool = False
    cancel: bool = False


class FlowAlignmentWatchV10_7:
    """Wait intrabar for flow after direction is confirmed on completed bars."""

    def __init__(self, config: FlowAlignmentWatchConfigV10_7 | None = None) -> None:
        self.config = config or FlowAlignmentWatchConfigV10_7()
        self.state: FlowAlignmentWatchStateV10_7 | None = None

    def arm(
        self,
        *,
        side: str,
        candle_time: int,
        decision_time: int,
        decision_price: float,
        atr14: float | None,
        opposing_levels: tuple[float, ...],
    ) -> FlowAlignmentWatchStateV10_7:
        side = str(side).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError(f"invalid side: {side}")
        if float(decision_price) <= 0:
            raise ValueError("decision_price must be positive")
        self.state = FlowAlignmentWatchStateV10_7(
            side=side,
            candle_time=int(candle_time),
            decision_time=int(decision_time),
            decision_price=float(decision_price),
            expiry_time=int(decision_time) + self.config.lifetime_ms,
            atr14=None if atr14 is None else float(atr14),
            opposing_levels=tuple(float(level) for level in opposing_levels),
        )
        return self.state

    def cancel(self) -> FlowAlignmentWatchStateV10_7 | None:
        prior = self.state
        self.state = None
        return prior

    def observe(
        self,
        *,
        price: float,
        event_time: int,
        trade_count_60s: int,
        flow_imbalance_60s: float,
    ) -> FlowAlignmentObservationV10_7:
        state = self.state
        if state is None:
            return FlowAlignmentObservationV10_7("IDLE", "NO_WATCH")
        event_time = int(event_time)
        price = float(price)
        if event_time <= state.decision_time:
            return FlowAlignmentObservationV10_7("WAIT", "PRE_DECISION_TRADE")
        if event_time > state.expiry_time:
            return FlowAlignmentObservationV10_7("CANCEL", "EXPIRED", cancel=True)
        state.observations += 1

        signed_move_bps = (
            (price - state.decision_price) / state.decision_price * 10_000.0
            if state.side == "LONG"
            else (state.decision_price - price) / state.decision_price * 10_000.0
        )
        if signed_move_bps > self.config.maximum_chase_bps:
            return FlowAlignmentObservationV10_7("CANCEL", "MOVE_ALREADY_CHASED", cancel=True)
        if signed_move_bps < 0:
            state.first_aligned_time = None
            return FlowAlignmentObservationV10_7("WAIT", "PRICE_NOT_CONFIRMED")

        count_ok = int(trade_count_60s) >= self.config.minimum_trade_count_60s
        imbalance = float(flow_imbalance_60s)
        flow_ok = (
            imbalance >= self.config.minimum_abs_flow_imbalance
            if state.side == "LONG"
            else imbalance <= -self.config.minimum_abs_flow_imbalance
        )
        if not count_ok or not flow_ok:
            state.first_aligned_time = None
            reason = "INSUFFICIENT_FLOW_TRADES" if not count_ok else "FLOW_NOT_ALIGNED"
            return FlowAlignmentObservationV10_7("WAIT", reason)
        if state.first_aligned_time is None:
            state.first_aligned_time = event_time
            return FlowAlignmentObservationV10_7("CONFIRMING", "FLOW_ALIGNMENT_STARTED")
        if event_time - state.first_aligned_time < self.config.confirmation_ms:
            return FlowAlignmentObservationV10_7("CONFIRMING", "FLOW_HOLD_TIME")
        return FlowAlignmentObservationV10_7("TRIGGER", "FLOW_CONFIRMED", trigger=True)
