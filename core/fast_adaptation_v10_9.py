from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FastInitialEntryConfigV10_9:
    lifetime_ms: int = 180_000
    break_buffer_bps: float = 1.0
    confirmation_ms: int = 1_000
    minimum_trade_count_60s: int = 20
    minimum_abs_flow_imbalance: float = 0.05
    maximum_chase_bps: float = 12.0

    def __post_init__(self) -> None:
        if self.lifetime_ms <= 0 or self.confirmation_ms <= 0:
            raise ValueError("entry timing values must be positive")
        if self.break_buffer_bps <= 0 or self.maximum_chase_bps <= 0:
            raise ValueError("entry price thresholds must be positive")
        if self.minimum_trade_count_60s <= 0:
            raise ValueError("minimum trade count must be positive")
        if not 0 < self.minimum_abs_flow_imbalance < 1:
            raise ValueError("entry imbalance must be between zero and one")


@dataclass
class FastInitialEntryStateV10_9:
    side: str
    candle_time: int
    decision_time: int
    decision_close: float
    decision_extreme: float
    expiry_time: int
    atr14: float | None
    opposing_levels: tuple[float, ...]
    first_confirmed_time: int | None = None
    observations: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FastAdaptationObservationV10_9:
    status: str
    reason: str
    trigger: bool = False
    cancel: bool = False


class FastInitialEntryWatchV10_9:
    """Authorize a flat entry from one completed signal plus live evidence."""

    def __init__(self, config: FastInitialEntryConfigV10_9 | None = None) -> None:
        self.config = config or FastInitialEntryConfigV10_9()
        self.state: FastInitialEntryStateV10_9 | None = None

    def arm(
        self,
        *,
        side: str,
        candle: dict[str, Any],
        atr14: float | None,
        opposing_levels: tuple[float, ...],
    ) -> FastInitialEntryStateV10_9:
        side = str(side).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError(f"invalid side: {side}")
        decision_time = int(candle["close_time"])
        close = float(candle["close"])
        extreme = float(candle["high"] if side == "LONG" else candle["low"])
        self.state = FastInitialEntryStateV10_9(
            side=side,
            candle_time=int(candle["time"]),
            decision_time=decision_time,
            decision_close=close,
            decision_extreme=extreme,
            expiry_time=decision_time + self.config.lifetime_ms,
            atr14=None if atr14 is None else float(atr14),
            opposing_levels=tuple(float(level) for level in opposing_levels),
        )
        return self.state

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
        state.observations += 1

        favorable_bps = (
            (price - state.decision_extreme) / state.decision_extreme * 10_000.0
            if state.side == "LONG"
            else (state.decision_extreme - price) / state.decision_extreme * 10_000.0
        )
        if favorable_bps > self.config.maximum_chase_bps:
            return FastAdaptationObservationV10_9(
                "CANCEL", "MOVE_ALREADY_CHASED", cancel=True
            )
        buffer = self.config.break_buffer_bps / 10_000.0
        threshold = (
            state.decision_extreme * (1.0 + buffer)
            if state.side == "LONG"
            else state.decision_extreme * (1.0 - buffer)
        )
        price_ok = price >= threshold if state.side == "LONG" else price <= threshold
        if not price_ok:
            state.first_confirmed_time = None
            return FastAdaptationObservationV10_9("WAIT", "DECISION_EXTREME_NOT_BROKEN")

        count_ok = int(trade_count_60s) >= self.config.minimum_trade_count_60s
        imbalance = float(flow_imbalance_60s)
        flow_ok = (
            imbalance >= self.config.minimum_abs_flow_imbalance
            if state.side == "LONG"
            else imbalance <= -self.config.minimum_abs_flow_imbalance
        )
        if not count_ok or not flow_ok:
            state.first_confirmed_time = None
            reason = "INSUFFICIENT_FLOW_TRADES" if not count_ok else "FLOW_NOT_ALIGNED"
            return FastAdaptationObservationV10_9("WAIT", reason)
        if state.first_confirmed_time is None:
            state.first_confirmed_time = event_time
            return FastAdaptationObservationV10_9("CONFIRMING", "FAST_ENTRY_STARTED")
        if event_time - state.first_confirmed_time < self.config.confirmation_ms:
            return FastAdaptationObservationV10_9("CONFIRMING", "FAST_ENTRY_HOLD")
        return FastAdaptationObservationV10_9("TRIGGER", "FAST_ENTRY_CONFIRMED", trigger=True)


@dataclass(frozen=True)
class FastIntrabarReversalConfigV10_9:
    lifetime_ms: int = 180_000
    ema_buffer_bps: float = 2.0
    extreme_break_bps: float = 1.0
    confirmation_ms: int = 2_000
    minimum_trade_count_60s: int = 20
    minimum_abs_flow_imbalance: float = 0.15
    maximum_chase_bps: float = 15.0

    def __post_init__(self) -> None:
        if self.lifetime_ms <= 0 or self.confirmation_ms <= 0:
            raise ValueError("reversal timing values must be positive")
        if min(self.ema_buffer_bps, self.extreme_break_bps, self.maximum_chase_bps) <= 0:
            raise ValueError("reversal price thresholds must be positive")
        if self.minimum_trade_count_60s <= 0:
            raise ValueError("minimum trade count must be positive")
        if not 0 < self.minimum_abs_flow_imbalance < 1:
            raise ValueError("reversal imbalance must be between zero and one")


@dataclass
class FastIntrabarReversalStateV10_9:
    base_side: str
    side: str
    candle_time: int
    decision_time: int
    decision_close: float
    decision_extreme: float
    slow_ema: float
    expiry_time: int
    atr14: float | None
    opposing_levels: tuple[float, ...]
    first_confirmed_time: int | None = None
    observations: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FastIntrabarReversalWatchV10_9:
    """Override a stale completed-bar bias only with strong live evidence."""

    def __init__(self, config: FastIntrabarReversalConfigV10_9 | None = None) -> None:
        self.config = config or FastIntrabarReversalConfigV10_9()
        self.state: FastIntrabarReversalStateV10_9 | None = None

    def arm(
        self,
        *,
        base_side: str,
        candle: dict[str, Any],
        slow_ema: float,
        atr14: float | None,
        opposing_levels: tuple[float, ...],
    ) -> FastIntrabarReversalStateV10_9:
        base_side = str(base_side).upper()
        if base_side not in {"LONG", "SHORT"}:
            raise ValueError(f"invalid base side: {base_side}")
        side = "LONG" if base_side == "SHORT" else "SHORT"
        decision_time = int(candle["close_time"])
        extreme = float(candle["high"] if side == "LONG" else candle["low"])
        self.state = FastIntrabarReversalStateV10_9(
            base_side=base_side,
            side=side,
            candle_time=int(candle["time"]),
            decision_time=decision_time,
            decision_close=float(candle["close"]),
            decision_extreme=extreme,
            slow_ema=float(slow_ema),
            expiry_time=decision_time + self.config.lifetime_ms,
            atr14=None if atr14 is None else float(atr14),
            opposing_levels=tuple(float(level) for level in opposing_levels),
        )
        return self.state

    def cancel(self) -> FastIntrabarReversalStateV10_9 | None:
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
    ) -> FastAdaptationObservationV10_9:
        state = self.state
        if state is None:
            return FastAdaptationObservationV10_9("IDLE", "NO_REVERSAL_WATCH")
        event_time = int(event_time)
        price = float(price)
        if event_time <= state.decision_time:
            return FastAdaptationObservationV10_9("WAIT", "PRE_DECISION_TRADE")
        if event_time > state.expiry_time:
            return FastAdaptationObservationV10_9("CANCEL", "EXPIRED", cancel=True)
        state.observations += 1

        chase_bps = (
            (price - state.decision_extreme) / state.decision_extreme * 10_000.0
            if state.side == "LONG"
            else (state.decision_extreme - price) / state.decision_extreme * 10_000.0
        )
        if chase_bps > self.config.maximum_chase_bps:
            return FastAdaptationObservationV10_9("CANCEL", "REVERSAL_ALREADY_CHASED", cancel=True)

        ema_buffer = self.config.ema_buffer_bps / 10_000.0
        break_buffer = self.config.extreme_break_bps / 10_000.0
        if state.side == "LONG":
            threshold = max(
                state.slow_ema * (1.0 + ema_buffer),
                state.decision_extreme * (1.0 + break_buffer),
            )
            price_ok = price >= threshold
        else:
            threshold = min(
                state.slow_ema * (1.0 - ema_buffer),
                state.decision_extreme * (1.0 - break_buffer),
            )
            price_ok = price <= threshold
        if not price_ok:
            state.first_confirmed_time = None
            return FastAdaptationObservationV10_9("WAIT", "REVERSAL_PRICE_NOT_CONFIRMED")

        count_ok = int(trade_count_60s) >= self.config.minimum_trade_count_60s
        imbalance = float(flow_imbalance_60s)
        flow_ok = (
            imbalance >= self.config.minimum_abs_flow_imbalance
            if state.side == "LONG"
            else imbalance <= -self.config.minimum_abs_flow_imbalance
        )
        if not count_ok or not flow_ok:
            state.first_confirmed_time = None
            reason = "INSUFFICIENT_FLOW_TRADES" if not count_ok else "REVERSAL_FLOW_NOT_ALIGNED"
            return FastAdaptationObservationV10_9("WAIT", reason)
        if state.first_confirmed_time is None:
            state.first_confirmed_time = event_time
            return FastAdaptationObservationV10_9("CONFIRMING", "REVERSAL_STARTED")
        if event_time - state.first_confirmed_time < self.config.confirmation_ms:
            return FastAdaptationObservationV10_9("CONFIRMING", "REVERSAL_HOLD")
        return FastAdaptationObservationV10_9("TRIGGER", "REVERSAL_CONFIRMED", trigger=True)


@dataclass(frozen=True)
class FastEvidenceExitConfigV10_9:
    confirmation_ms: int = 2_000
    minimum_trade_count_60s: int = 20
    minimum_abs_adverse_imbalance: float = 0.10
    maximum_losing_net_r: float = -0.20
    maximum_losing_gross_r: float = -0.05
    giveback_arm_net_r: float = 0.20
    giveback_exit_net_r: float = 0.05

    def __post_init__(self) -> None:
        if self.confirmation_ms <= 0 or self.minimum_trade_count_60s <= 0:
            raise ValueError("exit confirmation requirements must be positive")
        if not 0 < self.minimum_abs_adverse_imbalance < 1:
            raise ValueError("exit imbalance must be between zero and one")
        if self.maximum_losing_net_r >= 0:
            raise ValueError("maximum_losing_net_r must be negative")
        if self.maximum_losing_gross_r >= 0:
            raise ValueError("maximum_losing_gross_r must be negative")
        if self.giveback_arm_net_r <= self.giveback_exit_net_r:
            raise ValueError("giveback arm must exceed giveback exit")


@dataclass
class FastEvidenceExitStateV10_9:
    entry_event_time: int
    side: str
    peak_net_r: float
    first_adverse_time: int | None = None
    observations: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FastEvidenceExitV10_9:
    """Exit persistent adverse live evidence before the full stop is reached."""

    def __init__(self, config: FastEvidenceExitConfigV10_9 | None = None) -> None:
        self.config = config or FastEvidenceExitConfigV10_9()
        self.state: FastEvidenceExitStateV10_9 | None = None

    def reset(self) -> None:
        self.state = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "config": asdict(self.config),
            "state": None if self.state is None else self.state.as_dict(),
        }

    def observe(
        self,
        *,
        position: dict[str, Any],
        event_time: int,
        trade_count_60s: int,
        flow_imbalance_60s: float,
    ) -> FastAdaptationObservationV10_9:
        entry_time = int(position["entry_event_time"])
        side = str(position["position"])
        risk = float(position.get("planned_stop_loss") or 0.0)
        if risk <= 0:
            raise ValueError("position planned_stop_loss must be positive")
        net_r = float(position.get("current_pnl") or 0.0) / risk
        quantity = float(position.get("quantity") or 0.0)
        entry_fill = float(position.get("entry") or position.get("entry_fill") or 0.0)
        current_price = float(position.get("current_price") or entry_fill)
        gross_pnl = (
            (current_price - entry_fill) * quantity
            if side == "LONG"
            else (entry_fill - current_price) * quantity
        )
        gross_r = gross_pnl / risk
        if self.state is None or self.state.entry_event_time != entry_time:
            self.state = FastEvidenceExitStateV10_9(entry_time, side, net_r)
        state = self.state
        state.observations += 1
        state.peak_net_r = max(state.peak_net_r, net_r)
        if int(event_time) <= entry_time:
            return FastAdaptationObservationV10_9("WAIT", "ENTRY_TRADE")

        count_ok = int(trade_count_60s) >= self.config.minimum_trade_count_60s
        imbalance = float(flow_imbalance_60s)
        adverse_flow = (
            imbalance <= -self.config.minimum_abs_adverse_imbalance
            if side == "LONG"
            else imbalance >= self.config.minimum_abs_adverse_imbalance
        )
        # Entry/estimated-exit fees make a new position immediately negative.
        # Loss evidence therefore requires both poor net economics and actual
        # adverse price movement. A favorable gross move must never be called
        # a directional failure merely because costs have not been recovered.
        losing_failure = (
            net_r <= self.config.maximum_losing_net_r
            and gross_r <= self.config.maximum_losing_gross_r
        )
        profit_giveback = (
            state.peak_net_r >= self.config.giveback_arm_net_r
            and net_r <= self.config.giveback_exit_net_r
        )
        if not (count_ok and adverse_flow and (losing_failure or profit_giveback)):
            state.first_adverse_time = None
            return FastAdaptationObservationV10_9("WAIT", "EXIT_EVIDENCE_NOT_MET")
        if state.first_adverse_time is None:
            state.first_adverse_time = int(event_time)
            reason = "LOSS_EVIDENCE_STARTED" if losing_failure else "GIVEBACK_EVIDENCE_STARTED"
            return FastAdaptationObservationV10_9("CONFIRMING", reason)
        if int(event_time) - state.first_adverse_time < self.config.confirmation_ms:
            return FastAdaptationObservationV10_9("CONFIRMING", "EXIT_EVIDENCE_HOLD")
        reason = "LOSS_EVIDENCE_CONFIRMED" if losing_failure else "GIVEBACK_EVIDENCE_CONFIRMED"
        return FastAdaptationObservationV10_9("TRIGGER", reason, trigger=True)
