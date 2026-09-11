# TradingBot V10.9.2 — regime-aware fast adaptation

V10.9.2 corrects the countertrend behavior observed in V10.9.1. That version
opened LONG at 4409.29 while the completed direction and market regime were
SHORT / TREND_DOWN. A temporary buy-flow burst was mistaken for a reversal.

V10.9.2 keeps fast same-direction entries, but countertrend intrabar overrides
are permitted only when the causal completed-bar regime is `RANGE` or
`TRANSITION`. `TREND_DOWN` blocks LONG overrides and `TREND_UP` blocks SHORT
overrides. Unknown/warmup regimes also block the override.

The cost-aware V10.9.1 evidence-exit correction remains unchanged. The UI now
clears stale live-watch status when the signal is WAIT or both watches expire.

Close all older versions, then run:

```powershell
python terminal_v10_9_2.py
```

Verify with:

```powershell
python -m verify_v10_9_2
```

This remains paper-only and writes only to `runtime_v10_9_2`.
