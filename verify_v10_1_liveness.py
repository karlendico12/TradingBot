from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

from core.market_data_v10 import BinanceMarketDataV10

INTERVAL_MS = 180_000
ROOT = Path(__file__).resolve().parent / "runtime_v10_1"
DIAGNOSTICS = ROOT / "diagnostics_v10_1.sqlite3"
PAPER = ROOT / "paper_v10.sqlite3"
MARKET_DATA_FILE = Path(__file__).resolve().parent / "core" / "market_data_v10.py"


def utc_text(ms: int | None) -> str:
    if ms is None:
        return "--"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def scalar(con: sqlite3.Connection, sql: str, args=()):
    row = con.execute(sql, args).fetchone()
    return row[0] if row else None




async def probe_binance() -> None:
    market = BinanceMarketDataV10(symbol="XAUUSDT", interval="3m")
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            rows = await market._fetch_klines(session, limit=3)
            now_ms = int(time.time() * 1000)
            closed = [row for row in rows if int(row[6]) < now_ms]
            if closed:
                latest = closed[-1]
                print(
                    "REST latest closed candle          "
                    f"open={utc_text(int(latest[0]))} "
                    f"close={utc_text(int(latest[6]))}"
                )
            else:
                print("REST latest closed candle          NONE IN LAST 3 ROWS")

            trades = await market._fetch_aggregate_trades(session, limit=1)
            if trades:
                trade = trades[-1]
                print(
                    "REST latest aggregate trade        "
                    f"id={int(trade['a'])} time={utc_text(int(trade['T']))}"
                )
            else:
                print("REST latest aggregate trade        NONE")
    except Exception as exc:
        print(
            "REST connectivity                    FAILED "
            f"{type(exc).__name__}: {exc}"
        )


def main() -> int:
    print("=" * 76)
    print("TradingBot V10.1 - FEED / DECISION LIVENESS CHECK")
    print("=" * 76)
    print(f"integrity patch                    {BinanceMarketDataV10.integrity_version}")
    print(f"diagnostics DB                     {DIAGNOSTICS}")
    print(f"market-data file                   {MARKET_DATA_FILE}")
    asyncio.run(probe_binance())

    if not DIAGNOSTICS.exists():
        print(f"MISSING diagnostics DB: {DIAGNOSTICS}")
        return 2

    con = sqlite3.connect(f"file:{DIAGNOSTICS.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        count = int(scalar(con, "SELECT COUNT(*) FROM decisions") or 0)
        print(f"decisions                         {count}")
        if count == 0:
            print("status                            NO COMPLETED-BAR DECISIONS RECORDED")
            print("action                            keep bot open across a 3m close; inspect feed status")
        else:
            print("signals")
            for row in con.execute(
                "SELECT signal, COUNT(*) AS n FROM decisions GROUP BY signal ORDER BY signal"
            ):
                print(f"  {row['signal']:<12} {row['n']}")

            print("safety gates")
            for row in con.execute(
                "SELECT safety_gate, COUNT(*) AS n FROM decisions "
                "GROUP BY safety_gate ORDER BY safety_gate"
            ):
                print(f"  {row['safety_gate']:<20} {row['n']}")

            recent = list(
                con.execute(
                    "SELECT id, recorded_at, candle_time, decision_time, signal, "
                    "safety_gate, features_json FROM decisions ORDER BY id DESC LIMIT 12"
                )
            )
            latest = recent[0]
            now_ms = int(time.time() * 1000)
            age_ms = now_ms - int(latest["decision_time"])
            print(f"latest decision UTC               {utc_text(int(latest['decision_time']))}")
            print(f"latest decision age               {age_ms / 1000:.1f}s")

            chronological = sorted(recent, key=lambda r: int(r["candle_time"]))
            gaps = []
            for left, right in zip(chronological, chronological[1:]):
                delta = int(right["candle_time"]) - int(left["candle_time"])
                if delta != INTERVAL_MS:
                    gaps.append((int(left["candle_time"]), int(right["candle_time"]), delta))
            print(f"recent 3m timestamp gaps           {len(gaps)}")
            for left, right, delta in gaps[:5]:
                print(
                    "  GAP "
                    f"{utc_text(left)} -> {utc_text(right)} "
                    f"({delta / 1000:.0f}s)"
                )

            print("recent decisions")
            for row in recent[:8]:
                try:
                    features = json.loads(row["features_json"] or "{}")
                except json.JSONDecodeError:
                    features = {}
                source = features.get("candle_source", "--")
                recovered = features.get("candle_recovered", "--")
                eligible = features.get("entry_time_eligible", "--")
                trade_source = features.get("feed_source", "--")
                print(
                    f"  id={row['id']:>4} {utc_text(int(row['decision_time']))} "
                    f"sig={row['signal']:<5} gate={row['safety_gate']:<12} "
                    f"candle={source:<22} recovered={str(recovered):<5} "
                    f"entry_ok={str(eligible):<5} trades={trade_source}"
                )
    finally:
        con.close()

    if PAPER.exists():
        con = sqlite3.connect(f"file:{PAPER.as_posix()}?mode=ro", uri=True)
        try:
            trades = int(scalar(con, "SELECT COUNT(*) FROM trades") or 0)
            active = int(scalar(con, "SELECT COUNT(*) FROM active_position") or 0)
            interruptions = int(scalar(con, "SELECT COUNT(*) FROM interruptions") or 0)
            print(f"paper trades                       {trades}")
            print(f"active positions                   {active}")
            print(f"interruptions                      {interruptions}")
        finally:
            con.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
