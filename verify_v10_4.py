from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from core.adaptive_portfolios_v10_3 import AdaptivePortfolioEngineV10_3
from core.market_data_v10 import BinanceMarketDataV10


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime_v10_4"


def value(label: str, item: object) -> None:
    print(f"{label:<38} {item}")


def read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def iso_time(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).isoformat()


def pf_text(gains: object, losses: object) -> str:
    gain = float(gains or 0.0)
    loss = float(losses or 0.0)
    return "--" if loss == 0.0 else f"{gain / loss:.3f}"


def main() -> int:
    print("\n######## TradingBot V10.4 - PROFIT-PROTECTION CHECK ########")
    value("integrity patch", BinanceMarketDataV10.integrity_version)
    value("runtime", RUNTIME)
    value("profit guard", "arm +0.50R / lock +0.10R / trail 0.40R")
    value("daily trade-count cap", "OFF")
    value("position model", "ONE ACTUAL PAPER POSITION")

    diagnostics = RUNTIME / "diagnostics_v10_1.sqlite3"
    paper = RUNTIME / "paper_v10.sqlite3"
    adaptive = RUNTIME / "adaptive_portfolios_v10_3.sqlite3"
    if not diagnostics.exists():
        print("\nNo V10.4 runtime yet. Start `python terminal_v10_4.py` first.")
        return 2

    print("\n######## FEED / DECISION LIVENESS ########")
    with read_only(diagnostics) as connection:
        total = int(connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0])
        value("decisions", total)
        sources = {
            str(row["source"]): int(row["n"])
            for row in connection.execute(
                "SELECT json_extract(features_json,'$.candle_source') AS source, "
                "COUNT(*) AS n FROM decisions GROUP BY source"
            )
        }
        value("decision candle sources", sources)
        if total:
            latest = connection.execute(
                "SELECT decision_time, signal, safety_gate, features_json "
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
                value("LIVENESS", "STALE: bot is stopped or feed is not progressing")

    print("\n######## ACTUAL PROFIT-PROTECTED PAPER PORTFOLIO ########")
    if paper.exists():
        with read_only(paper) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS n,
                    COALESCE(SUM(net_pnl>0),0) AS wins,
                    COALESCE(SUM(gross_pnl),0) AS gross,
                    COALESCE(SUM(fees),0) AS fees,
                    COALESCE(SUM(net_pnl),0) AS net
                FROM trades
                """
            ).fetchone()
            value("closed trades", int(row["n"]))
            value("wins", int(row["wins"]))
            value("gross P/L", f"${float(row['gross']):+.2f}")
            value("fees", f"${float(row['fees']):.2f}")
            value("net P/L", f"${float(row['net']):+.2f}")
            active = int(connection.execute("SELECT COUNT(*) FROM active_position").fetchone()[0])
            value("active position", active)
            for reason in connection.execute(
                "SELECT reason, COUNT(*) AS n, COALESCE(SUM(net_pnl),0) AS net "
                "FROM trades GROUP BY reason ORDER BY n DESC"
            ):
                value(
                    f"exit {reason['reason']}",
                    f"N={int(reason['n'])} net=${float(reason['net']):+.2f}",
                )

    print("\n######## V10.3 SHADOW POLICY COMPARISON ########")
    if adaptive.exists():
        with read_only(adaptive) as connection:
            for policy in AdaptivePortfolioEngineV10_3.policies:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS n, AVG(net_r) AS mean_r,
                        COALESCE(SUM(net_r),0) AS total_r,
                        SUM(CASE WHEN net_r>0 THEN net_r ELSE 0 END) AS gains,
                        ABS(SUM(CASE WHEN net_r<0 THEN net_r ELSE 0 END)) AS losses,
                        COUNT(DISTINCT date(entry_event_time/1000,'unixepoch')) AS days
                    FROM adaptive_trades
                    WHERE policy=? AND status='CLOSED'
                    """,
                    (policy,),
                ).fetchone()
                mean = "--" if row["mean_r"] is None else f"{float(row['mean_r']):+.4f}R"
                value(
                    policy,
                    f"N={int(row['n'])} days={int(row['days'])} mean={mean} "
                    f"total={float(row['total_r']):+.2f}R "
                    f"PF={pf_text(row['gains'], row['losses'])}",
                )

    print("\n######## INTERPRETATION ########")
    print("PROFIT PROTECT is useful only if it improves total net P/L and drawdown")
    print("without destroying target winners. Do not judge it from one screenshot.")
    print("Collect at least 30 protected-paper exits over 10 active UTC dates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
