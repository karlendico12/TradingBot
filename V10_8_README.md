# TradingBot V10.8

V10.8 addresses the measured V10.7 bottleneck: raw 3x3 pivots created many
minor support/resistance levels only a few basis points away, so even confirmed
live-flow and breakout events were rejected.

V10.8 clusters nearby confirmed pivots into zones. A zone affects the actual
target only when it has at least two touches or a pivot with at least 0.50 ATR
of local prominence. All inputs are completed and causally confirmed.

The actual paper gate is controlled but less restrictive:

- minimum target room: 18 bps;
- minimum estimated net reward: 0.35 all-in R;
- modeled round-trip fee and slippage remain approximately 10 bps;
- 2-ATR target cap remains.

The prior V10.7 raw-level 30-bp/0.75R target decision is recorded as strict
shadow evidence. Direction confirmation, live-flow watches, structural-break
watches, anti-chase, neutral-first reversals, profit protection, and all feed
integrity rules remain.

Close every other version, then run:

```powershell
python terminal_v10_8.py
```

Inspect the separate runtime:

```powershell
python -m verify_v10_8
```

Require at least 30 closed trades across 10 active UTC dates, positive net P/L
after costs, and profit factor above 1.10 before considering promotion.
