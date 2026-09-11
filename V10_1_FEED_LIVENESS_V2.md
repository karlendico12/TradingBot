# TradingBot V10.1 Feed Liveness V2

## Why V2
The first liveness patch detected silent kline and aggregate-trade channels independently from bookTicker. It still treated any kline preview frame as proof that the candle feed was healthy. A stream can therefore remain active with forming-candle updates while the final closed-candle event is missed, leaving V10.1 with zero completed-bar decisions.

## V2 invariant
The integrity loop now verifies the expected latest completed 3-minute bar from wall-clock time. If `last_candle_time` is behind that completed-bar boundary, REST candle recovery runs even when recent kline preview frames are still arriving.

## Visibility
Feed status is printed to the terminal with `[FEED]` and every persisted completed-bar decision is printed with `[DECISION]`.

## Safety preserved
- SignalEngineV9 unchanged.
- V10 execution configuration unchanged.
- Old recovered candle signals are recorded but cannot enter retroactively.
- Old REST aggregate trades are diagnostic-only; only fresh prints can execute.
- Candle/trade deduplication remains enabled.
- Structure/order-flow diagnostics remain observational only.

## Validation
Full V8/V9/V10/V10.1 test suite: 43 passed, 0 failed.
