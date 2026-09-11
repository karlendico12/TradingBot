# TradingBot V10.9 — Fast Adaptation (paper only)

V10.9 is a separate forward-paper experiment. It does not reuse V10.8 P/L.

## What changed

- Actual flat entry no longer waits for two completed 3-minute signals.
- After the first actionable completed signal, a live watch requires a 1 bp
  break of that candle's extreme, aligned 60-second order flow, and a 1-second
  hold. A 12 bp anti-chase limit applies.
- A guarded intrabar override can oppose a stale completed-bar direction. It
  must reclaim the slow EMA, break the completed candle's opposite extreme,
  show stronger aligned flow (`|imbalance| >= 0.15`), and persist for 2 seconds.
- An open position can exit early when adverse flow persists for 2 seconds and
  the trade is at or below -0.20R, or after a +0.20R peak gives back to +0.05R.
- There is no same-print flip. After an evidence/signal exit, re-entry requires
  two completed signals.
- V10.8 significant structural targets, realistic fees/slippage, hard stop,
  target, V10.4 profit guard, one-position rule, and cap-OFF setting remain.

## Run

Close every older bot instance, then:

```powershell
python terminal_v10_9.py
```

Check the separate runtime:

```powershell
python verify_v10_9.py
```

This remains paper-only. Judge it after at least 30 closed trades across at
least 10 active UTC dates, and inspect entry types separately.
