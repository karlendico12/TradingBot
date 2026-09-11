from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from core.market_data_v10 import BinanceMarketDataV10


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime_v10_2"


def value(label: str, item: object) -> None:
    print(f"{label:<34} {item}")


def read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def iso_time(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).isoformat()


def main() -> int:
    print("\n######## TradingBot V10.2 - INTEGRITY / SHADOW CHECK ########")
    value("integrity patch", BinanceMarketDataV10.integrity_version)
    value("market WebSocket", BinanceMarketDataV10.market_stream_base)
    value("public WebSocket", BinanceMarketDataV10.public_stream_base)
    value("runtime", RUNTIME)

    diagnostics_path = RUNTIME / "diagnostics_v10_1.sqlite3"
    paper_path = RUNTIME / "paper_v10.sqlite3"
    shadow_path = RUNTIME / "shadow_outcomes_v10_2.sqlite3"
    if not diagnostics_path.exists():
        print("\nNo V10.2 runtime yet. Start `python terminal_v10_2.py` first.")
        return 2

    with read_only(diagnostics_path) as connection:
        total = connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        value("decisions", total)
        if total:
            latest = connection.execute(
                "SELECT recorded_at, decision_time, signal, safety_gate, features_json "
                "FROM decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            features = json.loads(latest["features_json"])
            now_ms = int(time.time() * 1000)
            value("latest decision UTC", iso_time(int(latest["decision_time"])))
            value(
                "latest decision age",
                f"{max(0.0, (now_ms - int(latest['decision_time'])) / 1000):.1f}s",
            )
            value("latest signal / gate", f"{latest['signal']} / {latest['safety_gate']}")
            value("candle source", features.get("candle_source", "--"))
            value("trade source", features.get("feed_source", "--"))
            value(
                "split sockets at decision",
                f"market={features.get('market_ws_connected')} "
                f"public={features.get('public_ws_connected')}",
            )
            value(
                "channel ages at decision",
                f"kline={features.get('kline_ws_age_s')}s "
                f"trade={features.get('agg_trade_ws_age_s')}s "
                f"book={features.get('book_ws_age_s')}s",
            )
            value(
                "book snapshot",
                f"source={features.get('book_source')} "
                f"spread={features.get('spread_bps')}bps",
            )

    if paper_path.exists():
        with read_only(paper_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(net_pnl),0) AS pnl FROM trades"
            ).fetchone()
            active = connection.execute(
                "SELECT COUNT(*) FROM active_position"
            ).fetchone()[0]
            value("paper closed trades", int(row["n"]))
            value("paper net P/L", f"${float(row['pnl']):+.2f}")
            value("paper active positions", active)

    if shadow_path.exists():
        with read_only(shadow_path) as connection:
            counts = {
                row["status"]: int(row["n"])
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS n FROM shadow_candidates GROUP BY status"
                )
            }
            row = connection.execute(
                "SELECT COUNT(*) AS n, AVG(net_r) AS mean_r, "
                "SUM(CASE WHEN net_r>0 THEN net_r ELSE 0 END) AS gains, "
                "ABS(SUM(CASE WHEN net_r<0 THEN net_r ELSE 0 END)) AS losses "
                "FROM shadow_candidates WHERE status='CLOSED'"
            ).fetchone()
            losses = float(row["losses"] or 0.0)
            gains = float(row["gains"] or 0.0)
            value("shadow status counts", counts)
            value("shadow closed", int(row["n"]))
            value(
                "shadow mean R",
                "--" if row["mean_r"] is None else f"{float(row['mean_r']):+.4f}",
            )
            value(
                "shadow profit factor",
                "--" if losses == 0 else f"{gains / losses:.3f}",
            )

    print("\nUse this report for liveness and data collection only; it is not a promotion gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
