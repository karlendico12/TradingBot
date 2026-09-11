# TradingBot V10 — forward paper measurement

V10 preserves the V9 EMA signal and replaces the unreliable execution and
accounting layer. It is **paper only** and is not evidence that V9 is profitable.

## Start

From PowerShell:

```powershell
cd C:\Users\Acer\Desktop\TradingBot\TradingBot
python terminal_v10.py
```

Install dependencies first if needed:

```powershell
python -m pip install -r requirements.txt
```

## Frozen assumptions

- XAUUSDT, completed 3-minute decisions
- unchanged V9 EMA 5/13 + ATR-gap + slope signal
- entry on the next observed aggregate trade, never the prior candle close
- maximum entry delay: 5 seconds after the decision timestamp
- 1.00% equity risk budget
- 0.20% price stop and 2R price target
- maximum notional: 3.0x current paper equity
- fee: 0.04% per side
- adverse slippage: 1 bp per side
- one position at a time; opposite signal reverses on an observed trade
- no daily entry cap for this paper run

## Feed integrity

V10 prefers Binance's aggregate-trade WebSocket. If a connection completes but
no frames arrive for 15 seconds, the status changes to `DEGRADED FEED` and V10
retrieves every unseen aggregate trade by ID through REST. It retries WebSocket
after 60 seconds. Every trade records its entry and exit source so WebSocket and
REST-replay results can be separated later.

Missing completed candles are replayed for indicator continuity only. V10 does
not open stale trades from candles missed while disconnected.

## Shutdown and storage

Closing the window cancels pending entries and closes an open paper position at
the last observed market price with normal exit slippage and fees. A hard power
loss can leave an active position with an unknowable offline path; on the next
launch V10 quarantines that position and excludes it from P/L.

SQLite is the source of truth:

```text
runtime_v10\paper_v10.sqlite3
```

A convenience CSV is regenerated after each close:

```text
runtime_v10\trades_v10.csv
```

V9 files and V9 paper history are not modified.

## Verification

```powershell
python -m unittest test_v10_core.py test_v9_core.py test_v8_core.py -v
```

Do not add support/resistance, candle patterns, or ML during this measurement
run. First collect enough cost-aware trades to determine whether the unchanged
V9 hypothesis has any net edge.

