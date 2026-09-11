# TradingBot V10.1 — structural diagnostics and safety

V10.1 keeps the V9 EMA signal and V10 cost-aware execution unchanged. New
market information is recorded for later evaluation; it does not silently tune
or filter the strategy.

## Run

```powershell
cd C:\Users\Acer\Desktop\TradingBot\TradingBot
python terminal_v10_1.py
```

## New chart and dashboard information

- yellow downward triangles: swing highs confirmed after three later 3m bars
- cyan upward triangles: swing lows confirmed after three later 3m bars
- dotted yellow/cyan lines: latest confirmed liquidity references
- UTC session classification
- causal candle-pattern label
- deterministic trend/range/shock regime label
- prior-60-second aggressor buy/sell imbalance
- aggregate-trade activity, turnover, spread and book freshness
- diagnostic strategy-health state based only on prior closed trades

## Trade telemetry

Each executed trade records:

- the complete feature snapshot at decision time
- entry latency in milliseconds
- entry and exit feed sources
- MFE and MAE in initial price-risk units
- time to MFE and MAE
- number of observed aggregate trades while the position was open

## Safety gates

Only two V10.1 additions can block a new entry:

1. no aggregate trade within 10 seconds of the decision timestamp;
2. realized UTC-day loss at or below 2% of estimated day-start equity.

Existing positions retain their V10 stop, target, reversal and shutdown rules.
The daily-loss guard does not force-close an already-open position.

## Storage

V10.1 uses separate files and does not mix results with V10:

```text
runtime_v10_1\paper_v10.sqlite3
runtime_v10_1\trades_v10.csv
runtime_v10_1\diagnostics_v10_1.sqlite3
```

## Verification

```powershell
python -m unittest test_v10_1_diagnostics.py test_v10_core.py test_v9_core.py test_v8_core.py -v
```

Do not interpret a swing arrow as an automatic buy or sell. The marker becomes
known only after the third right-hand candle completes. Structure, patterns,
regimes, order flow and health remain diagnostic until a separately declared
validation demonstrates stable improvement after costs.

## Feed-liveness hardening

V10.1 now checks the kline, aggregate-trade and book channels independently.
A busy `bookTicker` stream can no longer make a silent kline or aggTrade channel
look healthy. After 10 seconds of channel silence, the corresponding REST
integrity path becomes active and is rechecked every 2 seconds.

Important execution-integrity behavior:

- missing completed candles are deduplicated and sent through the normal decision
  callback, so V10.1 records a decision for recovered 3m bars;
- an old recovered candle may be recorded diagnostically, but it cannot create a
  new paper entry once its decision is more than the configured 5-second entry
  window old;
- recovered aggregate trades always update order-flow diagnostics, but only REST
  trades within the same 5-second freshness window may reach paper execution;
- stale REST aggregate trades cannot retroactively open or close a paper trade;
- order-flow and book snapshots exclude observations newer than the recovered
  candle decision time, preventing future-data contamination.

The recovered-candle timing rule is an execution-integrity rule, not a new
strategy filter. The V9 signal logic and V10 fee, slippage, risk and notional
assumptions remain unchanged.

### Liveness verification

After the bot has been open across at least one completed 3m boundary, run:

```powershell
python verify_v10_1_liveness.py
```

The report shows total decisions, signal/safety counts, latest decision age,
recent candle-source metadata and any gaps in recent 3m decision timestamps.
