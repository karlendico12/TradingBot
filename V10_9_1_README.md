# TradingBot V10.9.1 — cost-aware fast adaptation

This version corrects the V10.9 evidence-exit classification bug observed on
2026-09-07. V10.9 entered SHORT at 4399.10 and exited at 4397.80 even though
the gross price move was favorable. Fees made net R negative, so the old rule
incorrectly classified the trade as a directional failure.

V10.9.1 requires both:

- net P/L at or below -0.20R; and
- gross price P/L at or below -0.05R.

Profit-giveback exits no longer impose the two-completed-signal re-entry
penalty. Genuine adverse-price and signal-to-neutral exits retain it.

Close older instances and run:

```powershell
python terminal_v10_9_1.py
```

Verify with:

```powershell
python -m verify_v10_9_1
```

This is paper-only and uses the separate `runtime_v10_9_1` directory.
