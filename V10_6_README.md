# TradingBot V10.6

V10.6 keeps V10.5's confirmed entries, target-feasibility gate,
neutral-first reversal handling, cooldown, costs, stop, and profit guard. It
adds one causal intrabar pathway for moves that V10.5 could not reconsider.

When a completed-bar LONG/SHORT setup is rejected specifically because a
confirmed opposing structural level leaves too little target room, V10.6 arms
a watch for the remainder of that three-minute decision interval. It enters
only if all of these occur:

- genuine aggregate trades pass at least 2 bps beyond the level;
- price remains beyond it for at least one second;
- prior-60-second aggressor flow has at least 20 trades and an aligned absolute
  imbalance of at least 0.05;
- a fresh calculation to the next target still has at least 30 bps of room and
  at least 0.75R estimated net reward after fees and slippage.

The watch cancels on a one-bp reclaim, a new completed decision, expiry, an
existing position, or shutdown. It does not turn arbitrary green/red forming
candles into trades.

Close every other bot version, then run:

```powershell
python terminal_v10_6.py
```

Inspect its separate runtime with:

```powershell
python -m verify_v10_6
```

Do not combine V10.6 results with prior versions. Require at least 30 closed
trades across 10 active UTC dates, positive net P/L after costs, and PF above
1.10 before considering further promotion.
