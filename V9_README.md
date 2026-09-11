# TradingBot V9 - Filtered Fixed 2R

V9 is built from the V8 Fixed 2R baseline. V8 files are left intact.

## What changed

- Keeps XAUUSDT and the 3-minute closed-candle decision timeframe.
- Keeps EMA 5 / EMA 13 as the base directional signal.
- Keeps the existing stop-loss, quantity/risk calculation and fixed 1:2 take-profit logic.
- Adds a confirmation filter before LONG/SHORT is allowed:
  - EMA gap must be at least 0.10 x ATR(14).
  - Slow EMA must slope in the trade direction.
  - Candle close must be on the correct side of the slow EMA.
- Weak signals return `WAIT` with an explicit reason in the GUI and terminal.
- Uses separate files: `trades_v9.csv` and `active_position_v9.json`.
- Restores realized Total P/L from the CSV on restart.
- Writes a real UTC close timestamp to each new V9 CSV trade.
- Retains the V8 chart pan/zoom, live-price SL/TP checks, paper trading, persistence, and graceful shutdown behavior.

## Purpose of the V9 filter

V8's main weakness in the first paper test was repeated EMA reversals during choppy conditions. V9 deliberately changes only entry/reversal confirmation while keeping Fixed 2R unchanged, so V8 and V9 can be compared cleanly.

## Run

```powershell
python terminal_v9.py
```

## Paper trading only

V9 does not enable live Binance order execution. Keep it in paper mode while comparing it with V8.

## Testing

```powershell
python -m unittest test_v8_core.py test_v9_core.py
```

At build time, all 12 V8+V9 focused tests passed.

## Restart note

Active paper positions are persisted. As with V8, a long offline gap can make a restored paper position stale if SL/TP would have been crossed while the program was not running. For clean forward tests after a long shutdown, start flat or reconcile the offline period before counting the restored trade.
