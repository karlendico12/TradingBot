from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AdaptivePortfolioConfigV10_3:
    """Frozen comparison assumptions; these portfolios never route real orders."""

    stop_loss_percent: float = 0.002
    reward_ratio: float = 2.0
    fee_rate: float = 0.0004
    slippage_bps: float = 1.0
    entry_delay_ms: int = 5_000
    confirmation_bars: int = 2

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000.0


@dataclass
class PendingAction:
    action: str
    side: str | None
    candle_time: int
    decision_time: int
    features: dict[str, Any]


class AdaptivePortfolioEngineV10_3:
    """Causal, cost-aware comparison of five single-position policies.

    IMMEDIATE mirrors the present reversal behavior. ADAPTIVE exits on the
    first opposite decision, then requires two consecutive directional 3m
    decisions and directionally aligned prior-60s aggressor flow before it
    enters. HOLD ignores signal reversals. LONG_ONLY and SHORT_ONLY isolate the
    two directions. There is deliberately no daily trade-count limiter.
    """

    policies = (
        "IMMEDIATE",
        "ADAPTIVE",
        "HOLD",
        "LONG_ONLY",
        "SHORT_ONLY",
    )

    def __init__(
        self,
        database_path: Path,
        config: AdaptivePortfolioConfigV10_3 | None = None,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = config or AdaptivePortfolioConfigV10_3()
        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=5000")
        self._create_schema()
        self.positions: dict[str, dict[str, Any]] = {}
        self.pending: dict[str, PendingAction] = {}
        self.last_signal = "WAIT"
        self.signal_streak = 0
        self.censor_open("RESTART_GAP")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _create_schema(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS adaptive_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    policy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    side TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    candle_time INTEGER NOT NULL,
                    decision_time INTEGER NOT NULL,
                    entry_event_time INTEGER NOT NULL,
                    entry_source TEXT NOT NULL,
                    entry_market REAL NOT NULL,
                    entry_fill REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    target_price REAL NOT NULL,
                    all_in_stop_per_unit REAL NOT NULL,
                    features_json TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    exit_event_time INTEGER,
                    exit_source TEXT,
                    exit_market REAL,
                    exit_fill REAL,
                    exit_reason TEXT,
                    gross_pnl_per_unit REAL,
                    fees_per_unit REAL,
                    net_pnl_per_unit REAL,
                    net_r REAL,
                    observations INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_adaptive_policy_status "
                "ON adaptive_trades(policy, status)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_adaptive_entry_time "
                "ON adaptive_trades(entry_event_time)"
            )

    def _entry_fill(self, side: str, market_price: float) -> float:
        slip = self.config.slippage_rate
        return (
            market_price * (1.0 + slip)
            if side == "LONG"
            else market_price * (1.0 - slip)
        )

    def _exit_fill(self, side: str, market_price: float) -> float:
        slip = self.config.slippage_rate
        return (
            market_price * (1.0 - slip)
            if side == "LONG"
            else market_price * (1.0 + slip)
        )

    def _net_per_unit(
        self,
        side: str,
        entry_fill: float,
        market_price: float,
    ) -> tuple[float, float, float, float]:
        exit_fill = self._exit_fill(side, market_price)
        gross = (
            exit_fill - entry_fill
            if side == "LONG"
            else entry_fill - exit_fill
        )
        fees = self.config.fee_rate * (entry_fill + exit_fill)
        return gross - fees, gross, fees, exit_fill

    @staticmethod
    def _flow_aligned(side: str, features: dict[str, Any]) -> bool:
        try:
            trades = int(features.get("trade_count_60s") or 0)
            imbalance = float(features.get("flow_imbalance_60s") or 0.0)
        except (TypeError, ValueError):
            return False
        if trades <= 0:
            return False
        return imbalance > 0.0 if side == "LONG" else imbalance < 0.0

    def _queue(
        self,
        policy: str,
        action: str,
        side: str | None,
        candle_time: int,
        decision_time: int,
        features: dict[str, Any],
    ) -> None:
        self.pending[policy] = PendingAction(
            action=action,
            side=side,
            candle_time=int(candle_time),
            decision_time=int(decision_time),
            features=dict(features),
        )

    def on_decision(
        self,
        candle: dict[str, Any],
        signal: str,
        features: dict[str, Any],
        *,
        eligible: bool,
    ) -> None:
        """Consume one completed-bar decision without looking into its future."""
        if not eligible:
            return
        signal = str(signal).upper()
        actionable = signal in {"LONG", "SHORT"}
        if actionable and signal == self.last_signal:
            self.signal_streak += 1
        elif actionable:
            self.last_signal = signal
            self.signal_streak = 1
        else:
            self.last_signal = "WAIT"
            self.signal_streak = 0

        candle_time = int(candle["time"])
        decision_time = int(candle["close_time"])
        # A newer completed decision replaces any unexecuted action.
        self.pending.clear()

        immediate = self.positions.get("IMMEDIATE")
        if actionable:
            if immediate is None:
                self._queue(
                    "IMMEDIATE", "OPEN", signal, candle_time, decision_time, features
                )
            elif str(immediate["side"]) != signal:
                self._queue(
                    "IMMEDIATE", "REVERSE", signal, candle_time, decision_time, features
                )

        adaptive = self.positions.get("ADAPTIVE")
        if adaptive is not None and actionable and str(adaptive["side"]) != signal:
            # Protection and reversal are intentionally separate decisions.
            self._queue(
                "ADAPTIVE", "EXIT", None, candle_time, decision_time, features
            )
        elif (
            adaptive is None
            and actionable
            and self.signal_streak >= self.config.confirmation_bars
            and self._flow_aligned(signal, features)
        ):
            self._queue(
                "ADAPTIVE", "OPEN", signal, candle_time, decision_time, features
            )

        hold = self.positions.get("HOLD")
        if hold is None and actionable:
            self._queue("HOLD", "OPEN", signal, candle_time, decision_time, features)

        if self.positions.get("LONG_ONLY") is None and signal == "LONG":
            self._queue(
                "LONG_ONLY", "OPEN", "LONG", candle_time, decision_time, features
            )
        if self.positions.get("SHORT_ONLY") is None and signal == "SHORT":
            self._queue(
                "SHORT_ONLY", "OPEN", "SHORT", candle_time, decision_time, features
            )

    def _open_position(
        self,
        policy: str,
        action: PendingAction,
        market_price: float,
        event_time: int,
        source: str,
    ) -> None:
        side = str(action.side)
        if side not in {"LONG", "SHORT"} or policy in self.positions:
            return
        entry_fill = self._entry_fill(side, market_price)
        stop_distance = entry_fill * self.config.stop_loss_percent
        if side == "LONG":
            stop_price = entry_fill - stop_distance
            target_price = entry_fill + stop_distance * self.config.reward_ratio
        else:
            stop_price = entry_fill + stop_distance
            target_price = entry_fill - stop_distance * self.config.reward_ratio
        stop_net, _, _, _ = self._net_per_unit(side, entry_fill, stop_price)
        all_in_stop = abs(stop_net)
        now = self._now()
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO adaptive_trades(
                    policy, status, side, created_at, updated_at, candle_time,
                    decision_time, entry_event_time, entry_source, entry_market,
                    entry_fill, stop_price, target_price, all_in_stop_per_unit,
                    features_json, config_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    policy,
                    "OPEN",
                    side,
                    now,
                    now,
                    int(action.candle_time),
                    int(action.decision_time),
                    int(event_time),
                    str(source),
                    float(market_price),
                    entry_fill,
                    stop_price,
                    target_price,
                    all_in_stop,
                    json.dumps(action.features, sort_keys=True),
                    json.dumps(asdict(self.config), sort_keys=True),
                ),
            )
        self.positions[policy] = {
            "trade_id": int(cursor.lastrowid),
            "policy": policy,
            "side": side,
            "entry_event_time": int(event_time),
            "last_event_time": int(event_time),
            "entry_market": float(market_price),
            "entry_fill": entry_fill,
            "stop_price": stop_price,
            "target_price": target_price,
            "all_in_stop_per_unit": all_in_stop,
            "observations": 0,
        }

    def _close_position(
        self,
        policy: str,
        market_price: float,
        event_time: int,
        source: str,
        reason: str,
    ) -> None:
        position = self.positions.get(policy)
        if position is None:
            return
        net, gross, fees, exit_fill = self._net_per_unit(
            str(position["side"]),
            float(position["entry_fill"]),
            float(market_price),
        )
        risk = max(float(position["all_in_stop_per_unit"]), 1e-12)
        with self.connection:
            self.connection.execute(
                """
                UPDATE adaptive_trades SET
                    status='CLOSED', updated_at=?, exit_event_time=?,
                    exit_source=?, exit_market=?, exit_fill=?, exit_reason=?,
                    gross_pnl_per_unit=?, fees_per_unit=?, net_pnl_per_unit=?,
                    net_r=?, observations=?
                WHERE id=? AND status='OPEN'
                """,
                (
                    self._now(),
                    int(event_time),
                    str(source),
                    float(market_price),
                    exit_fill,
                    str(reason),
                    gross,
                    fees,
                    net,
                    net / risk,
                    int(position["observations"]),
                    int(position["trade_id"]),
                ),
            )
        self.positions.pop(policy, None)

    def _observe_position(
        self,
        policy: str,
        market_price: float,
        event_time: int,
        source: str,
    ) -> None:
        position = self.positions.get(policy)
        if position is None or event_time <= int(position["last_event_time"]):
            return
        position["last_event_time"] = int(event_time)
        position["observations"] = int(position["observations"]) + 1
        side = str(position["side"])
        stop_hit = (
            market_price <= float(position["stop_price"])
            if side == "LONG"
            else market_price >= float(position["stop_price"])
        )
        target_hit = (
            market_price >= float(position["target_price"])
            if side == "LONG"
            else market_price <= float(position["target_price"])
        )
        if stop_hit:
            self._close_position(policy, market_price, event_time, source, "STOP")
        elif target_hit:
            self._close_position(policy, market_price, event_time, source, "TARGET")

    def on_trade(self, trade: dict[str, Any]) -> None:
        event_time = int(trade["event_time"])
        market_price = float(trade["price"])
        source = str(trade.get("source", "UNKNOWN"))
        # Historical/recovered prints are valid path evidence after entry.
        for policy in self.policies:
            self._observe_position(policy, market_price, event_time, source)

        for policy, action in list(self.pending.items()):
            if event_time <= int(action.decision_time):
                continue
            delay = event_time - int(action.decision_time)
            if delay > self.config.entry_delay_ms:
                self.pending.pop(policy, None)
                continue
            if not bool(trade.get("entry_eligible", False)):
                continue
            self.pending.pop(policy, None)
            if action.action == "EXIT":
                self._close_position(
                    policy, market_price, event_time, source, "SIGNAL_TO_NEUTRAL"
                )
            elif action.action == "REVERSE":
                current = self.positions.get(policy)
                if current is not None and str(current["side"]) != str(action.side):
                    self._close_position(
                        policy, market_price, event_time, source, "REVERSAL"
                    )
                self._open_position(
                    policy, action, market_price, event_time, source
                )
            elif action.action == "OPEN":
                self._open_position(
                    policy, action, market_price, event_time, source
                )

    def censor_open(self, reason: str) -> int:
        now = self._now()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE adaptive_trades
                SET status='CENSORED', exit_reason=?, updated_at=?
                WHERE status='OPEN'
                """,
                (str(reason), now),
            )
        count = int(cursor.rowcount)
        self.positions.clear()
        self.pending.clear()
        return count

    def stats(self) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        for policy in self.policies:
            row = self.connection.execute(
                """
                SELECT COUNT(*) AS closed,
                    COALESCE(SUM(CASE WHEN net_r > 0 THEN 1 ELSE 0 END),0) AS wins,
                    AVG(net_r) AS mean_r,
                    COALESCE(SUM(net_r),0) AS total_r,
                    COALESCE(SUM(CASE WHEN net_r > 0 THEN net_r ELSE 0 END),0) AS gains,
                    ABS(COALESCE(SUM(CASE WHEN net_r < 0 THEN net_r ELSE 0 END),0)) AS losses
                FROM adaptive_trades
                WHERE policy=? AND status='CLOSED'
                """,
                (policy,),
            ).fetchone()
            censored = self.connection.execute(
                "SELECT COUNT(*) FROM adaptive_trades WHERE policy=? AND status='CENSORED'",
                (policy,),
            ).fetchone()[0]
            gains = float(row["gains"] or 0.0)
            losses = float(row["losses"] or 0.0)
            output[policy] = {
                "closed": int(row["closed"]),
                "wins": int(row["wins"]),
                "mean_r": None if row["mean_r"] is None else float(row["mean_r"]),
                "total_r": float(row["total_r"] or 0.0),
                "profit_factor": gains / losses if losses > 0 else None,
                "active": policy in self.positions,
                "censored": int(censored),
            }
        return output

    def close(self) -> None:
        self.connection.close()
