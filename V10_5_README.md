# TradingBot V10.5

V10.5 is a separate forward-paper experiment. It does not modify or reuse the
V10.4 paper ledger.

## Actual policy changes

- A new position requires two consecutive completed 3-minute signals and
  aligned causal aggressor flow from the prior 60 seconds.
- The first opposite completed-bar signal exits the position to neutral. It
  never opens the opposite direction on the same trade print.
- One complete 3-minute decision bar is skipped after a signal-to-neutral exit.
- Before entry, the next fresh aggregate trade is checked for available target
  room using only already-confirmed swing levels and completed-bar ATR.
- The target is the nearest of nominal 2R, buffered opposing structure, and a
  2-ATR cap.
- Entry is rejected when target room is below 30 bps or estimated reward after
  fees and slippage is below 0.75 all-in R.

V10.4 stop loss, position sizing, fees, slippage, profit protection, feed
watchdogs, single-position behavior, diagnostics, and shadow research remain.

## Run

Close every other TradingBot version, then:

```powershell
python terminal_v10_5.py
```

Check the accumulated result without modifying it:

```powershell
python -m verify_v10_5
```

V10.5 writes only to `runtime_v10_5`.

## Evidence gate

Do not promote from screenshots. Collect at least 30 closed trades across at
least 10 active UTC dates, then require positive net P/L after realistic costs,
profit factor above 1.10, and improvement in signal-to-neutral exits.
