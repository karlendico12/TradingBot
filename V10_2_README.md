# TradingBot V10.2 — integrity and independent shadow outcomes

V10.2 is the current forward-paper version. It does not claim profitability and
does not change the V9 EMA entry decision. It fixes the market-data transport,
improves paper execution integrity, and collects independent forward outcomes
for every timely LONG/SHORT signal.

## Run

Close every older TradingBot window, then use this exact project:

```powershell
cd "C:\Users\Acer\Desktop\TradingBot\New folder\TradingBot"
python terminal_v10_2.py
```

Do not run `terminal_v10.py` or `terminal_v10_1.py` beside V10.2. V10.2 has a
single-instance lock for its own launcher and stores results separately in:

```text
runtime_v10_2\paper_v10.sqlite3
runtime_v10_2\diagnostics_v10_1.sqlite3
runtime_v10_2\shadow_outcomes_v10_2.sqlite3
```

## What changed

- Binance regular market channels use `/market/stream`.
- Binance bookTicker uses a separate `/public/stream` connection.
- REST remains an independent per-channel watchdog.
- WebSocket and REST entry events must both pass the same wall-clock freshness
  gate.
- Replayed trades cannot open a position, but can resolve a stop or target that
  an already-open position crossed during a transient feed interruption.
- Shutdown closes only from a sufficiently recent observed trade; otherwise the
  unknown position is quarantined at the next launch.
- Book diagnostics keep a bounded quote history and use the latest quote at or
  before each decision.
- Every timely V9 LONG/SHORT decision receives an independent, potentially
  overlapping 60-minute outcome label with costs, MFE, MAE, and 5/15/30/60-minute
  milestones. Shadow candidates never route or resize the actual paper trade.

## Frozen paper assumptions

- XAUUSDT, completed 3-minute decisions
- V9 EMA 5/13 + ATR gap + slope signal
- next fresh aggregate trade entry, maximum delay 5 seconds
- 1% equity risk, maximum notional 3× equity
- raw stop 0.20%, raw target 2× the price stop
- fee 0.04% per side, adverse slippage 1 bp per side
- daily-loss threshold recorded but not enforced during this paper measurement

The raw 2× price target is only about 1.07R after the frozen fee/slippage model.
Do not call it a net 2R target.

## Verify

After the app crosses at least one completed 3-minute boundary:

```powershell
python verify_v10_2.py
python -m unittest test_v10_2_core.py test_v10_1_diagnostics.py test_v10_core.py test_v9_core.py test_v8_core.py -v
```

Keep V10.2 paper-only. Before any live-money work, use actual account commission
rates, exchange filters, exchange-hosted protective orders, and authenticated
order/fill updates.
