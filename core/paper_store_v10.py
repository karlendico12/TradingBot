from __future__ import annotations

import csv
import json
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PaperStoreV10:
    """SQLite is the source of truth; CSV is a derived convenience export."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.database_path.with_name("trades_v10.csv")
        # The Qt GUI owns construction, then the dedicated asyncio worker owns
        # all runtime database access. Cross-thread handoff is intentional and
        # serialized by the bot runner.
        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS active_position (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    close_time TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_market REAL NOT NULL,
                    entry_fill REAL NOT NULL,
                    exit_market REAL NOT NULL,
                    exit_fill REAL NOT NULL,
                    quantity REAL NOT NULL,
                    reason TEXT NOT NULL,
                    gross_pnl REAL NOT NULL,
                    fees REAL NOT NULL,
                    funding_pnl REAL NOT NULL,
                    net_pnl REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    entry_event_time INTEGER NOT NULL,
                    exit_event_time INTEGER NOT NULL,
                    candle_time INTEGER NOT NULL,
                    entry_source TEXT NOT NULL DEFAULT 'UNKNOWN',
                    exit_source TEXT NOT NULL DEFAULT 'UNKNOWN',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            columns = {
                row["name"]
                for row in self.connection.execute("PRAGMA table_info(trades)").fetchall()
            }
            if "entry_source" not in columns:
                self.connection.execute(
                    "ALTER TABLE trades ADD COLUMN entry_source TEXT NOT NULL DEFAULT 'UNKNOWN'"
                )
            if "exit_source" not in columns:
                self.connection.execute(
                    "ALTER TABLE trades ADD COLUMN exit_source TEXT NOT NULL DEFAULT 'UNKNOWN'"
                )
            if "metadata_json" not in columns:
                self.connection.execute(
                    "ALTER TABLE trades ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS interruptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    detected_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def save_position(self, position: dict[str, Any]) -> None:
        payload = json.dumps(position, separators=(",", ":"), sort_keys=True)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO active_position(singleton, payload, updated_at)
                VALUES(1, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (payload, self._now()),
            )

    def load_active_position(self) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT payload FROM active_position WHERE singleton=1"
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def quarantine_interrupted_position(self) -> dict[str, Any] | None:
        position = self.load_active_position()
        if position is None:
            return None
        with self.connection:
            self.connection.execute(
                "INSERT INTO interruptions(detected_at, reason, payload) VALUES(?,?,?)",
                (self._now(), "OFFLINE_PATH_UNKNOWN", json.dumps(position, sort_keys=True)),
            )
            self.connection.execute("DELETE FROM active_position WHERE singleton=1")
        return position

    def commit_close(self, trade: dict[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO trades(
                    close_time, side, entry_market, entry_fill, exit_market,
                    exit_fill, quantity, reason, gross_pnl, fees, funding_pnl,
                    net_pnl, balance_after, entry_event_time, exit_event_time,
                    candle_time, entry_source, exit_source, metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self._now(),
                    trade["position"],
                    trade["entry_market"],
                    trade["entry"],
                    trade["exit_market"],
                    trade["exit"],
                    trade["quantity"],
                    trade["reason"],
                    trade["gross_pnl"],
                    trade["fees"],
                    trade.get("funding_pnl", 0.0),
                    trade["net_pnl"],
                    trade["balance_after"],
                    trade["entry_event_time"],
                    trade["exit_event_time"],
                    trade["candle_time"],
                    trade.get("entry_source", "UNKNOWN"),
                    trade.get("exit_source", "UNKNOWN"),
                    json.dumps(trade.get("metadata", {}), sort_keys=True),
                ),
            )
            self.connection.execute("DELETE FROM active_position WHERE singleton=1")
        try:
            self.export_csv()
        except OSError as exc:
            # SQLite is authoritative. A locked/open CSV export must not turn a
            # successfully committed paper close into a fatal execution error.
            warnings.warn(f"Trade committed, but CSV export failed: {exc}")

    def stats(self) -> dict[str, float | int]:
        row = self.connection.execute(
            """
            SELECT
                COUNT(*) AS trades,
                COALESCE(SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
                COALESCE(SUM(CASE WHEN net_pnl <= 0 THEN 1 ELSE 0 END), 0) AS losses,
                COALESCE(SUM(net_pnl), 0.0) AS total_pnl
            FROM trades
            """
        ).fetchone()
        return {
            "trades": int(row["trades"]),
            "wins": int(row["wins"]),
            "losses": int(row["losses"]),
            "total_pnl": float(row["total_pnl"]),
        }

    def daily_net_pnl(self, utc_date: str) -> float:
        row = self.connection.execute(
            """
            SELECT COALESCE(SUM(net_pnl), 0.0) AS net_pnl
            FROM trades
            WHERE substr(close_time, 1, 10) = ?
            """,
            (str(utc_date),),
        ).fetchone()
        return float(row["net_pnl"])

    def recent_net_pnls(self, limit: int = 20) -> list[float]:
        rows = self.connection.execute(
            "SELECT net_pnl FROM trades ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [float(row["net_pnl"]) for row in reversed(rows)]

    def export_csv(self) -> None:
        rows = self.connection.execute(
            "SELECT * FROM trades ORDER BY id"
        ).fetchall()
        temporary = self.csv_path.with_suffix(".csv.tmp")
        fields = [
            "id", "close_time", "side", "entry_market", "entry_fill",
            "exit_market", "exit_fill", "quantity", "reason", "gross_pnl",
            "fees", "funding_pnl", "net_pnl", "balance_after",
            "entry_event_time", "exit_event_time", "candle_time",
            "entry_source", "exit_source",
            "metadata_json",
        ]
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row[field] for field in fields})
        temporary.replace(self.csv_path)

    def close(self) -> None:
        self.connection.close()
