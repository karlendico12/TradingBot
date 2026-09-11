# TradingBot V10.4 — cost-aware profit protection

V10.4 is a separate forward-paper experiment. It keeps the V9 completed-3m
entry signal, V10 feed integrity, V10.3 adaptive shadow comparisons, original
stop, and original target. Its one actual paper portfolio adds a causal
aggregate-trade profit guard.

## Frozen profit guard

All thresholds use **net R after modeled fees and slippage**, not candle colour
or unrealized price movement before costs.

1. Before the position reaches `+0.50R`, only the original stop, target,
   reversal, and shutdown rules operate.
2. At `+0.50R`, profit protection arms.
3. The protected floor becomes the greater of `+0.10R` and
   `peak net R - 0.40R`.
4. The floor can tighten but never loosen.
5. If observed net R retraces to the floor while still positive, the position
   closes as `PROFIT PROTECT` on that observed aggregate-trade price.
6. If price gaps through the positive floor into a loss, V10.4 cannot promise a
   profitable fill. The original stop/reversal remains responsible.

A red candle by itself is not an exit because candle colour is noisy and does
not quantify whether the move can cover trading costs.

## Run

Close the currently running V10.3 window first. Starting V10.4 creates a clean,
separate `runtime_v10_4` dataset.

```powershell
cd "C:\Users\Acer\Desktop\TradingBot\New folder\TradingBot"
python terminal_v10_4.py
```

V10.4 remains single-position and has no daily trade-count cap.

## Dashboard

The maximized dashboard keeps live price, signal, position, P/L, and the profit
guard visible above the chart. The resizable right panel separates detailed
information into `Position`, `Performance`, `Diagnostics`, and `Research` tabs.
Use `Latest 60`, `Latest 120`, `Follow Live`, and `Reset Y` above the chart;
drag horizontally to pan and use the mouse wheel to zoom.

## Verify

```powershell
python verify_v10_4.py
python -m unittest test_v10_4_profit_protection.py test_v10_3_adaptive.py test_v10_2_core.py test_v10_1_diagnostics.py test_v10_core.py test_v9_core.py test_v8_core.py -v
```

Do not conclude that profit protection works from one visual example. Require
at least 30 actual closed trades across 10 active UTC dates, then compare total
net P/L, drawdown, target retention, and the `PROFIT PROTECT` exit distribution.

This remains paper-only. Real execution would require authenticated order/fill
updates and exchange-hosted protective orders; a local application cannot
guarantee an exit price during gaps or disconnections.
