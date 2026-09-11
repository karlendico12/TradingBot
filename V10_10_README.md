# TradingBot V10.10 — completed-one-minute adaptive execution

V10.10 replaces the actual three-minute entry clock with genuine completed
one-minute decisions. Three-minute bars remain causal context for regime,
structure, safety, diagnostics, and target planning.

## Execution

- REST seeds 200 completed one-minute bars at startup; no historical trade is
  executed.
- Live aggregate trades build subsequent one-minute OHLCV bars.
- A same-direction or non-trend-context signal can arm after one completed 1m
  signal. A direction opposing a 3m trend requires two consecutive 1m signals
  and stronger flow.
- Entry requires a 0.5 bp break of the completed 1m extreme, aligned rolling
  60-second flow held for 0.5 seconds, and no more than a 10 bp chase.
- An opposite completed 1m signal with aligned flow exits to neutral. It never
  flips on the same print.
- V10.9.1 gross-aware evidence exits, V10.4 profit protection, realistic costs,
  V10.8 structural targets, and the one-position model remain.

Close older bot versions, then run:

```powershell
python terminal_v10_10.py
```

Verify with:

```powershell
python -m verify_v10_10
```

V10.10 is paper-only and writes to `runtime_v10_10`.
