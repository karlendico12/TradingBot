from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.execution_v10 import ExecutionConfig


@dataclass(frozen=True)
class TargetFeasibilityConfigV10_5:
    """Predeclared cost/structure requirements for a V10.5 paper entry."""

    structure_lookback_bars: int = 40
    level_buffer_atr: float = 0.05
    level_buffer_bps: float = 1.0
    maximum_target_atr: float = 2.0
    minimum_room_bps: float = 30.0
    minimum_net_reward_r: float = 0.75

    def __post_init__(self) -> None:
        if self.structure_lookback_bars < 7:
            raise ValueError("structure lookback must cover at least seven bars")
        if self.level_buffer_atr < 0 or self.level_buffer_bps < 0:
            raise ValueError("target buffers cannot be negative")
        if self.maximum_target_atr <= 0:
            raise ValueError("maximum_target_atr must be positive")
        if self.minimum_room_bps <= 0:
            raise ValueError("minimum_room_bps must be positive")
        if self.minimum_net_reward_r <= 0:
            raise ValueError("minimum_net_reward_r must be positive")


@dataclass(frozen=True)
class TargetEvaluationV10_5:
    accepted: bool
    reason: str
    side: str
    entry_market: float
    entry_fill: float
    stop_market: float
    fixed_target_market: float
    structural_level: float | None
    structural_target_market: float | None
    atr_target_market: float | None
    selected_target_market: float
    target_source: str
    room_bps: float
    estimated_net_reward_r: float
    estimated_roundtrip_cost_bps: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class StructuralTargetPlannerV10_5:
    """Select a causal target and reject entries without economical room.

    Only levels already confirmed at the completed-bar decision may be passed
    to this planner. It never looks at a forming or future candle.
    """

    def __init__(
        self,
        config: TargetFeasibilityConfigV10_5 | None = None,
    ) -> None:
        self.config = config or TargetFeasibilityConfigV10_5()

    @staticmethod
    def _entry_fill(side: str, market: float, execution: ExecutionConfig) -> float:
        slip = execution.slippage_rate
        return market * (1.0 + slip) if side == "LONG" else market * (1.0 - slip)

    @staticmethod
    def _exit_fill(side: str, market: float, execution: ExecutionConfig) -> float:
        slip = execution.slippage_rate
        return market * (1.0 - slip) if side == "LONG" else market * (1.0 + slip)

    def evaluate(
        self,
        side: str,
        market_price: float,
        execution: ExecutionConfig,
        *,
        atr14: float | None,
        opposing_levels: Iterable[float] = (),
        include_atr_cap: bool = True,
    ) -> TargetEvaluationV10_5:
        side = str(side).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError(f"invalid side: {side}")
        market = float(market_price)
        if market <= 0:
            raise ValueError("market_price must be positive")

        entry_fill = self._entry_fill(side, market, execution)
        stop_distance = entry_fill * execution.stop_loss_percent
        if side == "LONG":
            stop_market = entry_fill - stop_distance
            fixed_target = entry_fill + stop_distance * execution.reward_ratio
        else:
            stop_market = entry_fill + stop_distance
            fixed_target = entry_fill - stop_distance * execution.reward_ratio

        visible = sorted({float(level) for level in opposing_levels if float(level) > 0})
        if side == "LONG":
            ahead = [level for level in visible if level > entry_fill]
            structural_level = min(ahead) if ahead else None
        else:
            ahead = [level for level in visible if level < entry_fill]
            structural_level = max(ahead) if ahead else None

        atr = None if atr14 is None else float(atr14)
        if atr is not None and atr <= 0:
            atr = None
        buffer = max(
            market * self.config.level_buffer_bps / 10_000.0,
            (atr or 0.0) * self.config.level_buffer_atr,
        )
        structural_target = None
        if structural_level is not None:
            structural_target = (
                structural_level - buffer
                if side == "LONG"
                else structural_level + buffer
            )

        atr_target = None
        if atr is not None:
            atr_target = (
                market + atr * self.config.maximum_target_atr
                if side == "LONG"
                else market - atr * self.config.maximum_target_atr
            )

        candidates: list[tuple[str, float]] = [("FIXED_2R", fixed_target)]
        if structural_target is not None:
            candidates.append(("STRUCTURE", structural_target))
        if atr_target is not None and include_atr_cap:
            candidates.append(("ATR_CAP", atr_target))
        source, selected = (
            min(candidates, key=lambda item: item[1])
            if side == "LONG"
            else max(candidates, key=lambda item: item[1])
        )

        direction_ok = selected > market if side == "LONG" else selected < market
        room_bps = abs(selected - market) / market * 10_000.0 if direction_ok else 0.0
        target_exit_fill = self._exit_fill(side, selected, execution)
        stop_exit_fill = self._exit_fill(side, stop_market, execution)
        target_gross = (
            target_exit_fill - entry_fill
            if side == "LONG"
            else entry_fill - target_exit_fill
        )
        target_fees = execution.fee_rate * (entry_fill + target_exit_fill)
        target_net = target_gross - target_fees
        stop_gross = abs(entry_fill - stop_exit_fill)
        stop_fees = execution.fee_rate * (entry_fill + stop_exit_fill)
        all_in_stop = stop_gross + stop_fees
        net_reward_r = target_net / all_in_stop if all_in_stop > 0 else float("-inf")
        cost_per_unit = (
            abs(entry_fill - market)
            + abs(selected - target_exit_fill)
            + target_fees
        )
        cost_bps = cost_per_unit / market * 10_000.0

        if not direction_ok or target_net <= 0:
            accepted = False
            reason = "NO_POSITIVE_TARGET_ROOM"
        elif room_bps < self.config.minimum_room_bps:
            accepted = False
            reason = "ROOM_BELOW_MINIMUM"
        elif net_reward_r < self.config.minimum_net_reward_r:
            accepted = False
            reason = "NET_REWARD_BELOW_MINIMUM"
        else:
            accepted = True
            reason = "PASS"

        return TargetEvaluationV10_5(
            accepted=accepted,
            reason=reason,
            side=side,
            entry_market=market,
            entry_fill=entry_fill,
            stop_market=stop_market,
            fixed_target_market=fixed_target,
            structural_level=structural_level,
            structural_target_market=structural_target,
            atr_target_market=atr_target,
            selected_target_market=selected,
            target_source=source,
            room_bps=room_bps,
            estimated_net_reward_r=net_reward_r,
            estimated_roundtrip_cost_bps=cost_bps,
        )


@dataclass
class PolicyDecisionV10_5:
    action: str
    reason: str
    side: str | None = None


class ConfirmedNeutralPolicyV10_5:
    """Exit an opposite signal to neutral; confirm any later re-entry."""

    def __init__(self, confirmation_bars: int = 2, cooldown_bars: int = 1) -> None:
        if confirmation_bars < 2:
            raise ValueError("confirmation_bars must be at least two")
        if cooldown_bars < 1:
            raise ValueError("cooldown_bars must be at least one")
        self.confirmation_bars = int(confirmation_bars)
        self.cooldown_bars = int(cooldown_bars)
        self.last_signal = "WAIT"
        self.signal_streak = 0
        self.cooldown_remaining = 0

    @staticmethod
    def flow_aligned(side: str, features: dict[str, Any]) -> bool:
        try:
            count = int(features.get("trade_count_60s") or 0)
            imbalance = float(features.get("flow_imbalance_60s") or 0.0)
        except (TypeError, ValueError):
            return False
        return count > 0 and (imbalance > 0 if side == "LONG" else imbalance < 0)

    def mark_signal_exit(self) -> None:
        self.cooldown_remaining = self.cooldown_bars

    def on_decision(
        self,
        signal: str,
        *,
        eligible: bool,
        current_side: str | None,
        features: dict[str, Any],
    ) -> PolicyDecisionV10_5:
        signal = str(signal).upper()
        actionable = signal in {"LONG", "SHORT"}
        if not eligible:
            self.last_signal = "WAIT"
            self.signal_streak = 0
            return PolicyDecisionV10_5("NONE", "INELIGIBLE")
        if actionable and signal == self.last_signal:
            self.signal_streak += 1
        elif actionable:
            self.last_signal = signal
            self.signal_streak = 1
        else:
            self.last_signal = "WAIT"
            self.signal_streak = 0

        current = None if current_side is None else str(current_side).upper()
        if current is not None:
            if actionable and signal != current:
                return PolicyDecisionV10_5("EXIT_TO_NEUTRAL", "FIRST_OPPOSITE", signal)
            return PolicyDecisionV10_5("NONE", "POSITION_HELD")

        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            return PolicyDecisionV10_5("NONE", "COOLDOWN")
        if not actionable:
            return PolicyDecisionV10_5("NONE", "WAIT")
        if self.signal_streak < self.confirmation_bars:
            return PolicyDecisionV10_5("NONE", "NEEDS_SECOND_SIGNAL", signal)
        if not self.flow_aligned(signal, features):
            return PolicyDecisionV10_5("NONE", "FLOW_NOT_ALIGNED", signal)
        return PolicyDecisionV10_5("OPEN", "CONFIRMED", signal)


class PolicyAuditStoreV10_5:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.execute("PRAGMA busy_timeout=5000")
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_time INTEGER NOT NULL,
                    candle_time INTEGER,
                    event_type TEXT NOT NULL,
                    side TEXT,
                    reason TEXT NOT NULL,
                    details_json TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_policy_event_type "
                "ON policy_events(event_type)"
            )

    def record(
        self,
        event_type: str,
        reason: str,
        *,
        event_time: int,
        candle_time: int | None = None,
        side: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO policy_events(
                    created_at,event_time,candle_time,event_type,side,reason,details_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    now,
                    int(event_time),
                    None if candle_time is None else int(candle_time),
                    str(event_type),
                    None if side is None else str(side),
                    str(reason),
                    json.dumps(details or {}, sort_keys=True),
                ),
            )

    def close(self) -> None:
        self.connection.close()
