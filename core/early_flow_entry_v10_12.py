"""Flow-persistent entry watch that does not chase a second price breakout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from core.fast_adaptation_v10_9 import (
    FastAdaptationObservationV10_9,
    FastInitialEntryStateV10_9,
)


@dataclass(frozen=True)
class EarlyFlowEntryConfigV10_12:
    lifetime_ms: int = 10_000
    confirmation_ms: int = 500
    minimum_trade_count_60s: int = 20
    minimum_abs_flow_imbalance: float = 0.05
    maximum_chase_bps: float = 5.0

    def __post_init__(self) -> None:
        if self.lifetime_ms <= 0 or self.confirmation_ms <= 0:
            raise ValueError("entry timing values must be positive")
        if self.minimum_trade_count_60s <= 0:
            raise ValueError("minimum trade count must be positive")
        if not 0 < self.minimum_abs_flow_imbalance < 1:
            raise ValueError("entry imbalance must be between zero and one")
        if self.maximum_chase_bps <= 0:
            raise ValueError("maximum chase must be positive")


class EarlyFlowEntryWatchV10_12:
    """Enter from a completed 1m direction after persistent live flow.

    Unlike V10.10/V10.11, this watch does not demand another break of the
    completed minute's extreme.  It still refuses stale, thin, misaligned, or
    already-chased prints.
    """

    def __init__(self, config: EarlyFlowEntryConfigV10_12) -> None:
        self.config = config
        self.state: FastInitialEntryStateV10_9 | None = None
        self.flow_valid_until: int | None = None
        self.last_observation_time: int | None = None
        self.maximum_gap_ms = 0
        self.maximum_adverse_bps = 0.0
        self.maximum_favorable_bps = 0.0
        self.confirmation_resets = 0
        self.last_audit_key: tuple[str, str] | None = None

    def arm_from(self, prior: FastInitialEntryStateV10_9) -> FastInitialEntryStateV10_9:
        self.flow_valid_until = None
        self.last_observation_time = None
        self.maximum_gap_ms = 0
        self.maximum_adverse_bps = 0.0
        self.maximum_favorable_bps = 0.0
        self.confirmation_resets = 0
        self.last_audit_key = None
        prior.expiry_time = prior.decision_time + self.config.lifetime_ms
        prior.first_confirmed_time = None
        prior.observations = 0
        self.state = prior
        return prior

    def reset_confirmation(self) -> None:
        if self.state is not None and self.state.first_confirmed_time is not None:
            self.confirmation_resets += 1
            self.state.first_confirmed_time = None
        self.flow_valid_until = None

    def diagnostics(self) -> dict[str, Any]:
        return {
            "last_observation_time": self.last_observation_time,
            "maximum_gap_ms": self.maximum_gap_ms,
            "maximum_adverse_bps": self.maximum_adverse_bps,
            "maximum_favorable_bps": self.maximum_favorable_bps,
            "confirmation_resets": self.confirmation_resets,
            "flow_valid_until": self.flow_valid_until,
        }

    def _next_flow_failure(
        self, trades: Iterable[dict[str, Any]], event_time: int,
    ) -> int:
        """First rolling-window expiry that invalidates flow without new prints.

        The tracker includes trades exactly 60 seconds old. Group simultaneous
        expiries so no imaginary intermediate imbalance resets confirmation.
        """
        groups: dict[int, list[float]] = {}
        for trade in trades:
            timestamp = int(trade["event_time"])
            if event_time - 60_000 <= timestamp <= event_time:
                group = groups.setdefault(timestamp + 60_001, [0, 0.0, 0.0])
                group[0] += 1
                group[2 if trade["buyer_is_maker"] else 1] += float(trade["quantity"])
        count = sum(group[0] for group in groups.values())
        buy = sum(group[1] for group in groups.values())
        sell = sum(group[2] for group in groups.values())
        for expiry, group in sorted(groups.items()):
            count -= group[0]
            buy -= group[1]
            sell -= group[2]
            total = buy + sell
            imbalance = (buy - sell) / total if total > 0 else 0.0
            aligned = imbalance if self.state.side == "LONG" else -imbalance
            if count < self.config.minimum_trade_count_60s or aligned < self.config.minimum_abs_flow_imbalance:
                return expiry
        return event_time

    def cancel(self) -> FastInitialEntryStateV10_9 | None:
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
        flow_trades: Iterable[dict[str, Any]] | None = None,
    ) -> FastAdaptationObservationV10_9:
        state = self.state
        if state is None:
            return FastAdaptationObservationV10_9("IDLE", "NO_ENTRY_WATCH")
        event_time = int(event_time)
        price = float(price)
        if event_time <= state.decision_time:
            return FastAdaptationObservationV10_9("WAIT", "PRE_DECISION_TRADE")
        if event_time > state.expiry_time:
            return FastAdaptationObservationV10_9("CANCEL", "EXPIRED", cancel=True)
        if self.last_observation_time is not None and event_time < self.last_observation_time:
            self.reset_confirmation()
            return FastAdaptationObservationV10_9("WAIT", "OUT_OF_ORDER_TRADE")
        if self.last_observation_time is not None:
            self.maximum_gap_ms = max(self.maximum_gap_ms, event_time - self.last_observation_time)
        self.last_observation_time = event_time
        expired_flow = self.flow_valid_until is not None and event_time >= self.flow_valid_until
        if expired_flow:
            self.reset_confirmation()
        state.observations += 1

        favorable_bps = (
            (price - state.decision_close) / state.decision_close * 10_000.0
            if state.side == "LONG"
            else (state.decision_close - price) / state.decision_close * 10_000.0
        )
        self.maximum_adverse_bps = max(self.maximum_adverse_bps, -favorable_bps)
        self.maximum_favorable_bps = max(self.maximum_favorable_bps, favorable_bps)
        if favorable_bps > self.config.maximum_chase_bps:
            return FastAdaptationObservationV10_9(
                "CANCEL", "MOVE_ALREADY_CHASED", cancel=True
            )

        count_ok = int(trade_count_60s) >= self.config.minimum_trade_count_60s
        imbalance = float(flow_imbalance_60s)
        flow_ok = (
            imbalance >= self.config.minimum_abs_flow_imbalance
            if state.side == "LONG"
            else imbalance <= -self.config.minimum_abs_flow_imbalance
        )
        if not count_ok or not flow_ok:
            self.reset_confirmation()
            reason = "INSUFFICIENT_FLOW_TRADES" if not count_ok else "FLOW_NOT_ALIGNED"
            return FastAdaptationObservationV10_9("WAIT", reason)
        if flow_trades is not None:
            self.flow_valid_until = self._next_flow_failure(flow_trades, event_time)
        if state.first_confirmed_time is None:
            state.first_confirmed_time = event_time
            reason = "ROLLING_FLOW_EXPIRED_RESTART" if expired_flow else "EARLY_FLOW_STARTED"
            return FastAdaptationObservationV10_9("CONFIRMING", reason)
        if event_time - state.first_confirmed_time < self.config.confirmation_ms:
            return FastAdaptationObservationV10_9("CONFIRMING", "EARLY_FLOW_HOLD")
        return FastAdaptationObservationV10_9(
            "TRIGGER", "EARLY_FLOW_CONFIRMED", trigger=True
        )
