# TradingBot V10.3 — adaptive policy lab

V10.3 is a forward-paper comparison, not a claim of profitability. The actual
paper portfolio still executes the frozen V9/V10.2 rule. V10.3 adds five causal
shadow portfolios so adaptation can be evaluated without changing the live
measurement halfway through the experiment.

## Run

Close V10, V10.1, and V10.2 first, then run:

```powershell
cd "C:\Users\Acer\Desktop\TradingBot\New folder\TradingBot"
python terminal_v10_3.py
```

V10.3 stores new observations separately in `runtime_v10_3`.

## Frozen comparison policies

- `IMMEDIATE`: current behavior; reverse on the next fresh trade after the
  first opposite completed 3-minute signal.
- `ADAPTIVE`: exit to neutral after the first opposite signal. Enter only after
  two consecutive directional 3-minute signals and matching causal prior-60s
  aggressor-flow direction.
- `HOLD`: ignore later signal flips and retain the position until stop/target.
- `LONG_ONLY`: take LONG signals only and hold to stop/target.
- `SHORT_ONLY`: take SHORT signals only and hold to stop/target.

All five use the same 0.20% raw stop, 2x raw target, 0.04% fee per side,
1 bp adverse slippage per side, and maximum five-second next-trade entry delay.
Recovered trades cannot create entries but can resolve an already-open
stop/target. No policy has a daily trade-count cap.

The `ADAPTIVE` rule uses flow observed at or before the completed-bar decision.
It never uses future flow to approve a historical entry. The direction check is
sign-only (`>0` for LONG, `<0` for SHORT); there is no fitted imbalance threshold.

## Verify

After at least one completed 3-minute decision:

```powershell
python verify_v10_3.py
python -m unittest test_v10_3_adaptive.py test_v10_2_core.py test_v10_1_diagnostics.py test_v10_core.py test_v9_core.py test_v8_core.py -v
```

Do not choose a winner from a single day. First require at least 30 closed
trades and 10 active UTC dates per policy, positive mean net R, profit factor
above 1.10, and stable direction across chronological blocks. LONG and SHORT
must also be inspected separately.

Keep this version paper-only. A real-money version additionally requires actual
account commissions, exchange filters, authenticated fill/order updates, and
exchange-hosted protective orders.
