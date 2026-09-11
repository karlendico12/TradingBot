# TradingBot V10.7

V10.7 addresses one measured V10.6 bottleneck: a direction could remain valid
for many completed bars while the bot discarded each entry because order flow
was not aligned at the exact close timestamp.

After at least two consecutive completed 3-minute signals, V10.7 keeps a
three-minute live flow watch when the initial flow check fails. It can enter
after flow aligns continuously for one second, provided there are at least 20
trades in the prior 60 seconds and absolute imbalance is at least 0.05.

The watch does not chase a move beyond 20 bps from the decision close. Every
entry is still required to have at least 30 bps of target room and at least
0.75R estimated net reward after fees and slippage. A structural-room failure
can transition into the V10.6 breakout watch.

V10.5 neutral-first reversal handling, one-bar cooldown, V10.6 structural
breakouts, V10.4 profit protection, realistic costs, and feed integrity remain.

Close every other bot version, then run:

```powershell
python terminal_v10_7.py
```

Inspect the separate runtime:

```powershell
python -m verify_v10_7
```

Require at least 30 closed trades across 10 active UTC dates, positive net P/L
after costs, and profit factor above 1.10 before considering promotion.
