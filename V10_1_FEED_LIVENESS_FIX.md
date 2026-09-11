# V10.1 feed-liveness fix

## Root cause

The combined Binance WebSocket used one receive timeout for all subscribed
streams. `bookTicker` could continue delivering frames while `kline` and
`aggTrade` were silent, so the socket looked alive even though the decision and
execution feeds had stopped. The existing missing-candle replay also routed
recovered bars through `history_callback`, which warms indicators but does not
produce V10.1 decision records.

## Fix

- independent liveness clocks for kline, aggTrade and bookTicker
- REST candle integrity loop when kline is silent
- REST aggregate-trade integrity loop when aggTrade is silent
- completed recovered candles go through the decision callback
- candle and aggregate-trade deduplication
- stale recovered candles cannot queue new entries
- stale REST trades are diagnostic-only and cannot execute retroactively
- near-live REST recovery remains execution-eligible only inside the configured
  five-second V10 entry window
- recovered order-flow/book diagnostics are causal and exclude future events
- WebSocket reconnect proceeds independently while REST integrity remains active

## Frozen behavior

SignalEngineV9 is unchanged. V10 fees, slippage, 1% risk sizing, 3x notional cap,
stop/target behavior and V10.1 daily-loss/data-staleness gates are unchanged.

## Verification performed

`python -m unittest -v test_v10_core.py test_v10_1_diagnostics.py test_v9_core.py test_v8_core.py`

Result: 42 tests passed, including a regression test that keeps the book channel
healthy while forcing kline and aggregate-trade channels stale.

A live Binance smoke test could not be performed in the build environment because
external DNS access to `fapi.binance.com` is unavailable there. Run the included
`verify_v10_1_liveness.py` locally after V10.1 has crossed a completed 3m candle.
