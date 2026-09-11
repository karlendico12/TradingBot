from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from core.market_data_v10 import BinanceMarketDataV10


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime_v10_11"


def value(label: str, item: object) -> None:
    print(f"{label:<58} {item}")


def read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def report(
    runtime: Path = RUNTIME,
    *,
    version: str = "V10.11",
    execution: str = "live aggTrade break + 0.5s flow confirmation",
) -> int:
    print(f"\n######## TradingBot {version} - STRUCTURAL FALLBACK CHECK ########")
    value("integrity patch", BinanceMarketDataV10.integrity_version)
    value("runtime", runtime)
    value("decision clock", "completed 1m")
    value("execution", execution)
    value("target correction", "confirmed structure may replace infeasible 2-ATR cap")
    value("economic gates", ">=18bps room / >=0.35 estimated net R")
    value("daily trade-count cap", "OFF")

    diagnostics = runtime / "diagnostics_v10_1.sqlite3"
    audit = runtime / "policy_audit_v10_5.sqlite3"
    paper = runtime / "paper_v10.sqlite3"
    if not diagnostics.exists():
        print(
            f"\nNo {version} runtime yet. Start its terminal script first."
        )
        return 2

    print("\n######## LIVENESS ########")
    with read_only(diagnostics) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0])
        value("3m context decisions", count)
        row = connection.execute(
            "SELECT decision_time,signal,safety_gate,features_json "
            "FROM decisions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            features = json.loads(row["features_json"])
            age = max(0.0, (int(time.time() * 1000) - int(row["decision_time"])) / 1000)
            value(
                "latest 3m context UTC",
                datetime.fromtimestamp(
                    int(row["decision_time"]) / 1000, tz=timezone.utc
                ).isoformat(),
            )
            value("latest 3m context age", f"{age:.1f}s")
            value("latest 3m signal / gate", f"{row['signal']} / {row['safety_gate']}")
            value("latest 3m regime", features.get("regime"))

    print("\n######## 1M EXECUTION FUNNEL ########")
    if audit.exists():
        with read_only(audit) as connection:
            for row in connection.execute(
                "SELECT event_type,reason,COUNT(*) n FROM policy_events "
                "WHERE event_type LIKE 'MICRO_%' "
                "OR event_type LIKE 'FAST_ENTRY_%' "
                "OR event_type LIKE 'STRUCTURAL_TARGET_%' "
                "GROUP BY event_type,reason ORDER BY event_type,reason"
            ):
                value(f"{row['event_type']} / {row['reason']}", int(row["n"]))

    print("\n######## PAPER PORTFOLIO ########")
    if paper.exists():
        with read_only(paper) as connection:
            row = connection.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(net_pnl>0),0) wins, "
                "COALESCE(SUM(gross_pnl),0) gross, COALESCE(SUM(fees),0) fees, "
                "COALESCE(SUM(net_pnl),0) net "
                "FROM trades"
            ).fetchone()
            value("closed trades", int(row["n"]))
            value("wins", int(row["wins"]))
            value("gross P/L", f"${float(row['gross']):+.2f}")
            value("fees", f"${float(row['fees']):.2f}")
            value("net P/L", f"${float(row['net']):+.2f}")
            value(
                "active position",
                int(connection.execute("SELECT COUNT(*) FROM active_position").fetchone()[0]),
            )

    print(f"\n{version} is a separate paper experiment; do not merge runtimes.")
    print("More entries are not evidence of profitability. Keep realistic costs enabled.")
    return 0


def main() -> int:
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
