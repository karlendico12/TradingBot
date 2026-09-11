from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ShadowConfigV10_2:
    """Frozen independent-label assumptions; never routes the paper portfolio."""

    stop_loss_percent: float = 0.002
    reward_ratio: float = 2.0
    fee_rate: float = 0.0004
    slippage_bps: float = 1.0
    entry_delay_ms: int = 5_000
    horizon_ms: int = 60 * 60 * 1_000

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000.0


class ShadowOutcomeEngineV10_2:
    """Independently label every timely V9 signal using observed trade paths.

    Candidates may overlap because they are research labels, not positions. A
    candidate enters only on a genuinely fresh trade after its completed-bar
    decision. Once open, all subsequently recovered trades remain valid path
    evidence and can close the label at stop, target, or the frozen one-hour
    horizon.
    """

    family = "V9_EMA_INDEPENDENT_60M"
    milestone_minutes = (5, 15, 30, 60)

    def __init__(
        self,
        database_path: Path,
        config: ShadowConfigV10_2 | None = None,
    ) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = config or ShadowConfigV10_2()
        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=5000")
        self._create_schema()
        self.active: dict[int, dict[str, Any]] = {}
        self.censor_unfinished("RESTART_GAP")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _create_schema(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shadow_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    identity TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    family TEXT NOT NULL,
                    status TEXT NOT NULL,
                    side TEXT NOT NULL,
                    candle_time INTEGER NOT NULL,
                    decision_time INTEGER NOT NULL,
                    features_json TEXT NOT NULL,
                    entry_event_time INTEGER,
                    entry_source TEXT,
                    entry_market REAL,
                    entry_fill REAL,
                    stop_price REAL,
                    target_price REAL,
                    all_in_stop_per_unit REAL,
                    exit_event_time INTEGER,
                    exit_source TEXT,
                    exit_market REAL,
                    exit_fill REAL,
                    exit_reason TEXT,
                    gross_pnl_per_unit REAL,
                    fees_per_unit REAL,
                    net_pnl_per_unit REAL,
                    net_r REAL,
                    mfe_r REAL,
                    mae_r REAL,
                    observations INTEGER NOT NULL DEFAULT 0,
                    milestones_json TEXT NOT NULL DEFAULT '{}',
                    config_json TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_shadow_status "
                "ON shadow_candidates(status)"
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_shadow_decision "
                "ON shadow_candidates(decision_time)"
            )

    def censor_unfinished(self, reason: str) -> int:
        now = self._now()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE shadow_candidates
                SET status='CENSORED', exit_reason=?, updated_at=?
                WHERE status IN ('PENDING', 'OPEN')
                """,
                (str(reason), now),
            )
        count = int(cursor.rowcount)
        self.active.clear()
        return count

    def add_candidate(
        self,
        candle: dict[str, Any],
        side: str,
        features: dict[str, Any],
    ) -> int | None:
        side = str(side).upper()
        if side not in {"LONG", "SHORT"}:
            return None
        candle_time = int(candle["time"])
        decision_time = int(candle["close_time"])
        identity = f"{decision_time}|{side}|{self.family}"
        now = self._now()
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO shadow_candidates(
                    identity, created_at, updated_at, family, status, side,
                    candle_time, decision_time, features_json, config_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    identity,
                    now,
                    now,
                    self.family,
                    "PENDING",
                    side,
                    candle_time,
                    decision_time,
                    json.dumps(features, sort_keys=True),
                    json.dumps(asdict(self.config), sort_keys=True),
                ),
            )
        if cursor.rowcount != 1:
            return None
        candidate_id = int(cursor.lastrowid)
        self.active[candidate_id] = {
            "id": candidate_id,
            "status": "PENDING",
            "side": side,
            "candle_time": candle_time,
            "decision_time": decision_time,
        }
        return candidate_id

    def _entry_fill(self, side: str, market_price: float) -> float:
        slip = self.config.slippage_rate
        if side == "LONG":
            return market_price * (1.0 + slip)
        return market_price * (1.0 - slip)

    def _exit_fill(self, side: str, market_price: float) -> float:
        slip = self.config.slippage_rate
        if side == "LONG":
            return market_price * (1.0 - slip)
        return market_price * (1.0 + slip)

    def _net_per_unit(
        self,
        side: str,
        entry_fill: float,
        market_price: float,
    ) -> tuple[float, float, float, float]:
        exit_fill = self._exit_fill(side, market_price)
        if side == "LONG":
            gross = exit_fill - entry_fill
        else:
            gross = entry_fill - exit_fill
        fees = self.config.fee_rate * (entry_fill + exit_fill)
        return gross - fees, gross, fees, exit_fill

    def _open_candidate(
        self,
        candidate: dict[str, Any],
        market_price: float,
        event_time: int,
        source: str,
    ) -> None:
        side = str(candidate["side"])
        entry_fill = self._entry_fill(side, market_price)
        stop_distance = entry_fill * self.config.stop_loss_percent
        if side == "LONG":
            stop_price = entry_fill - stop_distance
            target_price = entry_fill + stop_distance * self.config.reward_ratio
        else:
            stop_price = entry_fill + stop_distance
            target_price = entry_fill - stop_distance * self.config.reward_ratio
        stop_net, _, _, _ = self._net_per_unit(
            side,
            entry_fill,
            stop_price,
        )
        all_in_stop = abs(stop_net)
        candidate.update(
            {
                "status": "OPEN",
                "entry_event_time": int(event_time),
                "entry_source": str(source),
                "entry_market": float(market_price),
                "entry_fill": entry_fill,
                "stop_price": stop_price,
                "target_price": target_price,
                "all_in_stop_per_unit": all_in_stop,
                "last_event_time": int(event_time),
                "mfe_r": 0.0,
                "mae_r": 0.0,
                "observations": 0,
                "milestones": {},
            }
        )
        with self.connection:
            self.connection.execute(
                """
                UPDATE shadow_candidates SET
                    status='OPEN', entry_event_time=?, entry_source=?,
                    entry_market=?, entry_fill=?, stop_price=?, target_price=?,
                    all_in_stop_per_unit=?, updated_at=?
                WHERE id=?
                """,
                (
                    int(event_time),
                    str(source),
                    float(market_price),
                    entry_fill,
                    stop_price,
                    target_price,
                    all_in_stop,
                    self._now(),
                    int(candidate["id"]),
                ),
            )

    def _expire_candidate(self, candidate: dict[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE shadow_candidates
                SET status='EXPIRED', exit_reason='NO_TIMELY_NEXT_TRADE', updated_at=?
                WHERE id=?
                """,
                (self._now(), int(candidate["id"])),
            )
        self.active.pop(int(candidate["id"]), None)

    def _finalize_candidate(
        self,
        candidate: dict[str, Any],
        market_price: float,
        event_time: int,
        source: str,
        reason: str,
    ) -> None:
        net, gross, fees, exit_fill = self._net_per_unit(
            str(candidate["side"]),
            float(candidate["entry_fill"]),
            market_price,
        )
        risk = max(float(candidate["all_in_stop_per_unit"]), 1e-12)
        net_r = net / risk
        with self.connection:
            self.connection.execute(
                """
                UPDATE shadow_candidates SET
                    status='CLOSED', exit_event_time=?, exit_source=?,
                    exit_market=?, exit_fill=?, exit_reason=?,
                    gross_pnl_per_unit=?, fees_per_unit=?, net_pnl_per_unit=?,
                    net_r=?, mfe_r=?, mae_r=?, observations=?,
                    milestones_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    int(event_time),
                    str(source),
                    float(market_price),
                    exit_fill,
                    str(reason),
                    gross,
                    fees,
                    net,
                    net_r,
                    float(candidate["mfe_r"]),
                    float(candidate["mae_r"]),
                    int(candidate["observations"]),
                    json.dumps(candidate["milestones"], sort_keys=True),
                    self._now(),
                    int(candidate["id"]),
                ),
            )
        self.active.pop(int(candidate["id"]), None)

    def _observe_open_candidate(
        self,
        candidate: dict[str, Any],
        market_price: float,
        event_time: int,
        source: str,
    ) -> None:
        if event_time <= int(candidate["last_event_time"]):
            return
        candidate["last_event_time"] = int(event_time)
        candidate["observations"] = int(candidate["observations"]) + 1
        net, _, _, _ = self._net_per_unit(
            str(candidate["side"]),
            float(candidate["entry_fill"]),
            market_price,
        )
        risk = max(float(candidate["all_in_stop_per_unit"]), 1e-12)
        net_r = net / risk
        candidate["mfe_r"] = max(float(candidate["mfe_r"]), net_r)
        candidate["mae_r"] = max(float(candidate["mae_r"]), -net_r)
        elapsed = event_time - int(candidate["entry_event_time"])

        milestones: dict[str, Any] = candidate["milestones"]
        for minutes in self.milestone_minutes:
            key = f"{minutes}m"
            if key not in milestones and elapsed >= minutes * 60_000:
                milestones[key] = {
                    "event_time": int(event_time),
                    "market_price": float(market_price),
                    "net_r": net_r,
                }

        side = str(candidate["side"])
        stop_hit = (
            market_price <= float(candidate["stop_price"])
            if side == "LONG"
            else market_price >= float(candidate["stop_price"])
        )
        target_hit = (
            market_price >= float(candidate["target_price"])
            if side == "LONG"
            else market_price <= float(candidate["target_price"])
        )
        if stop_hit:
            self._finalize_candidate(
                candidate, market_price, event_time, source, "STOP"
            )
        elif target_hit:
            self._finalize_candidate(
                candidate, market_price, event_time, source, "TARGET"
            )
        elif elapsed >= self.config.horizon_ms:
            self._finalize_candidate(
                candidate, market_price, event_time, source, "60M_HORIZON"
            )

    def on_trade(self, trade: dict[str, Any]) -> None:
        event_time = int(trade["event_time"])
        market_price = float(trade["price"])
        source = str(trade.get("source", "UNKNOWN"))
        entry_eligible = bool(trade.get("entry_eligible", False))
        for candidate in list(self.active.values()):
            if candidate["status"] == "PENDING":
                decision_time = int(candidate["decision_time"])
                if event_time <= decision_time:
                    continue
                delay = event_time - decision_time
                if delay > self.config.entry_delay_ms:
                    self._expire_candidate(candidate)
                elif entry_eligible:
                    self._open_candidate(
                        candidate,
                        market_price,
                        event_time,
                        source,
                    )
                continue
            self._observe_open_candidate(
                candidate,
                market_price,
                event_time,
                source,
            )

    def stats(self) -> dict[str, Any]:
        counts = {
            str(row["status"]): int(row["count"])
            for row in self.connection.execute(
                "SELECT status, COUNT(*) AS count FROM shadow_candidates GROUP BY status"
            ).fetchall()
        }
        result = self.connection.execute(
            """
            SELECT
                COUNT(*) AS closed,
                COALESCE(SUM(CASE WHEN net_r > 0 THEN 1 ELSE 0 END), 0) AS wins,
                AVG(net_r) AS mean_r,
                SUM(CASE WHEN net_r > 0 THEN net_r ELSE 0 END) AS gains,
                ABS(SUM(CASE WHEN net_r < 0 THEN net_r ELSE 0 END)) AS losses
            FROM shadow_candidates WHERE status='CLOSED'
            """
        ).fetchone()
        gains = float(result["gains"] or 0.0)
        losses = float(result["losses"] or 0.0)
        return {
            "candidates": sum(counts.values()),
            "pending": counts.get("PENDING", 0),
            "open": counts.get("OPEN", 0),
            "closed": int(result["closed"]),
            "expired": counts.get("EXPIRED", 0),
            "censored": counts.get("CENSORED", 0),
            "wins": int(result["wins"]),
            "mean_r": (
                None if result["mean_r"] is None else float(result["mean_r"])
            ),
            "profit_factor": (gains / losses if losses > 0 else None),
        }

    def close(self) -> None:
        self.connection.close()
