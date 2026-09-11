from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from core.market_data_v10 import BinanceMarketDataV10


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime_v10_9"


def value(label: str, item: object) -> None:
    print(f"{label:<52} {item}")


def read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def iso_time(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).isoformat()


def pf_text(gain: object, loss: object) -> str:
    gains = float(gain or 0.0)
    losses = abs(float(loss or 0.0))
    return "--" if losses == 0 else f"{gains / losses:.3f}"


def main() -> int:
    print("\n######## TradingBot V10.9 - FAST ADAPTATION CHECK ########")
    value("integrity patch", BinanceMarketDataV10.integrity_version)
    value("runtime", RUNTIME)
    value("normal entry", "first 3m signal + live extreme break/flow")
    value("intrabar override", "EMA reclaim + opposite extreme + strong flow")
    value("fast evidence exit", "adverse flow at loss or profit giveback")
    value("target gate", ">=18bps room and >=0.35 estimated net R")
    value("daily trade-count cap", "OFF")

    diagnostics = RUNTIME / "diagnostics_v10_1.sqlite3"
    paper = RUNTIME / "paper_v10.sqlite3"
    audit = RUNTIME / "policy_audit_v10_5.sqlite3"
    if not diagnostics.exists():
        print("\nNo V10.9 runtime yet. Start `python terminal_v10_9.py` first.")
        return 2

    print("\n######## FEED / DECISION LIVENESS ########")
    with read_only(diagnostics) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0])
        value("decisions", count)
        if count:
            latest = connection.execute(
                "SELECT decision_time,signal,safety_gate,features_json "
                "FROM decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            features = json.loads(latest["features_json"])
            age = max(0.0, (int(time.time() * 1000) - int(latest["decision_time"])) / 1000)
            value("latest decision UTC", iso_time(int(latest["decision_time"])))
            value("latest decision age", f"{age:.1f}s")
            value("latest signal / gate", f"{latest['signal']} / {latest['safety_gate']}")
            value(
                "split sockets at decision",
                f"market={features.get('market_ws_connected')} "
                f"public={features.get('public_ws_connected')}",
            )
            if age > 240:
                value("LIVENESS", "STALE: bot stopped or feed not progressing")

    print("\n######## V10.9 EXECUTION FUNNEL ########")
    if audit.exists():
        with read_only(audit) as connection:
            for row in connection.execute(
                "SELECT event_type,reason,COUNT(*) AS n FROM policy_events "
                "GROUP BY event_type,reason ORDER BY event_type,reason"
            ):
                value(f"{row['event_type']} / {row['reason']}", int(row["n"]))

    print("\n######## ACTUAL V10.9 PAPER PORTFOLIO ########")
    if paper.exists():
        with read_only(paper) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS n,
                    COALESCE(SUM(net_pnl>0),0) AS wins,
                    COALESCE(SUM(gross_pnl),0) AS gross,
                    COALESCE(SUM(fees),0) AS fees,
                    COALESCE(SUM(funding_pnl),0) AS funding,
                    COALESCE(SUM(net_pnl),0) AS net,
                    COALESCE(SUM(CASE WHEN net_pnl>0 THEN net_pnl ELSE 0 END),0) AS gain,
                    COALESCE(SUM(CASE WHEN net_pnl<0 THEN net_pnl ELSE 0 END),0) AS loss,
                    COUNT(DISTINCT substr(close_time,1,10)) AS days
                FROM trades
                """
            ).fetchone()
            value("closed trades", int(row["n"]))
            value("active UTC dates", int(row["days"]))
            value("wins", int(row["wins"]))
            value("gross P/L", f"${float(row['gross']):+.2f}")
            value("fees", f"${float(row['fees']):.2f}")
            value("funding", f"${float(row['funding']):+.4f}")
            value("net P/L", f"${float(row['net']):+.2f}")
            value("profit factor", pf_text(row["gain"], row["loss"]))
            value(
                "active position",
                int(connection.execute("SELECT COUNT(*) FROM active_position").fetchone()[0]),
            )
            for reason in connection.execute(
                "SELECT reason,COUNT(*) AS n,COALESCE(SUM(net_pnl),0) AS net "
                "FROM trades GROUP BY reason ORDER BY n DESC"
            ):
                value(
                    f"exit {reason['reason']}",
                    f"N={int(reason['n'])} net=${float(reason['net']):+.2f}",
                )

    print("\n######## INTERPRETATION GATE ########")
    print("V10.9 is a new forward-paper experiment; do not merge prior P/L.")
    print("Fast does not imply profitable. Require >=30 closed trades over")
    print(">=10 active UTC dates, positive net P/L, and PF >1.10 after costs.")
    print("Compare FIRST_SIGNAL and FAST_REVERSAL entries separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
