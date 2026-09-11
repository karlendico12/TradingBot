from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from core.market_data_v10 import BinanceMarketDataV10


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime_v10_9_1"


def value(label: str, item: object) -> None:
    print(f"{label:<54} {item}")


def read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def pf_text(gain: object, loss: object) -> str:
    gains = float(gain or 0.0)
    losses = abs(float(loss or 0.0))
    return "--" if losses == 0 else f"{gains / losses:.3f}"


def main() -> int:
    print("\n######## TradingBot V10.9.1 - COST-AWARE FAST CHECK ########")
    value("integrity patch", BinanceMarketDataV10.integrity_version)
    value("runtime", RUNTIME)
    value("entry", "V10.9 first-signal + guarded intrabar override")
    value("loss evidence", "net<=-0.20R AND gross price P/L<=-0.05R")
    value("profit giveback", "no two-signal re-entry penalty")
    value("daily trade-count cap", "OFF")

    diagnostics = RUNTIME / "diagnostics_v10_1.sqlite3"
    paper = RUNTIME / "paper_v10.sqlite3"
    audit = RUNTIME / "policy_audit_v10_5.sqlite3"
    if not diagnostics.exists():
        print("\nNo V10.9.1 runtime yet. Start `python terminal_v10_9_1.py` first.")
        return 2

    print("\n######## LIVENESS ########")
    with read_only(diagnostics) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0])
        value("decisions", count)
        if count:
            row = connection.execute(
                "SELECT decision_time,signal,safety_gate FROM decisions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            age = max(0.0, (int(time.time() * 1000) - int(row["decision_time"])) / 1000)
            stamp = datetime.fromtimestamp(
                int(row["decision_time"]) / 1000, tz=timezone.utc
            ).isoformat()
            value("latest decision UTC", stamp)
            value("latest decision age", f"{age:.1f}s")
            value("latest signal / gate", f"{row['signal']} / {row['safety_gate']}")

    print("\n######## EXECUTION FUNNEL ########")
    if audit.exists():
        with read_only(audit) as connection:
            for row in connection.execute(
                "SELECT event_type,reason,COUNT(*) n FROM policy_events "
                "GROUP BY event_type,reason ORDER BY event_type,reason"
            ):
                value(f"{row['event_type']} / {row['reason']}", int(row["n"]))

    print("\n######## PAPER PORTFOLIO ########")
    if paper.exists():
        with read_only(paper) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) n, COALESCE(SUM(net_pnl>0),0) wins,
                  COALESCE(SUM(gross_pnl),0) gross, COALESCE(SUM(fees),0) fees,
                  COALESCE(SUM(net_pnl),0) net,
                  COALESCE(SUM(CASE WHEN net_pnl>0 THEN net_pnl ELSE 0 END),0) gain,
                  COALESCE(SUM(CASE WHEN net_pnl<0 THEN net_pnl ELSE 0 END),0) loss,
                  COUNT(DISTINCT substr(close_time,1,10)) days
                FROM trades
                """
            ).fetchone()
            value("closed trades", int(row["n"]))
            value("active UTC dates", int(row["days"]))
            value("wins", int(row["wins"]))
            value("gross P/L", f"${float(row['gross']):+.2f}")
            value("fees", f"${float(row['fees']):.2f}")
            value("net P/L", f"${float(row['net']):+.2f}")
            value("profit factor", pf_text(row["gain"], row["loss"]))
            value(
                "active position",
                int(connection.execute("SELECT COUNT(*) FROM active_position").fetchone()[0]),
            )
            for reason in connection.execute(
                "SELECT reason,COUNT(*) n,COALESCE(SUM(net_pnl),0) net "
                "FROM trades GROUP BY reason ORDER BY n DESC"
            ):
                value(
                    f"exit {reason['reason']}",
                    f"N={int(reason['n'])} net=${float(reason['net']):+.2f}",
                )

    print("\nV10.9.1 is separate paper evidence. Do not merge it with V10.9.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
