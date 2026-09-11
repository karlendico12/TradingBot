# TradingBot V8 fixes

This package keeps the original project structure and updates the V8 structured-code path.

## Fixed

- Live price updates now check stop-loss and take-profit, so protective exits can trigger between 3-minute candle closes.
- Live price updates now keep unrealized P/L in `PositionManager` and the GUI synchronized.
- Historical candles are routed to a warm-up-only callback and no longer execute live paper trades on startup.
- Reversal closes now use the normal closed-trade handler so CSV logging, total trades, wins, losses, and GUI statistics stay consistent.
- `current_pnl` is now connected to the GUI.
- Duplicate `stats` signal connection was removed.
- Printed risk amount now uses the calculated `risk_amount` instead of a hard-coded `$10.00`.
- Market-data manager resets its running state when restarted.
- Added `test_v8_core.py` with focused tests for LONG/SHORT SL/TP, unrealized P/L, duplicate-entry protection, and configurable risk amount.

## Safety note

V8 remains a paper-trading flow. The project contains `binance_executor.py`, but V8 does not submit live orders through it. Exchange precision, margin, fees, slippage, and liquidation controls should be added and tested before any live-futures integration.

## Follow-up UI startup fix
- Historical candles still warm up indicators only and do not execute trades.
- Added a history-complete callback so the GUI chart renders the 199 warmed-up candles immediately after startup.
- Added a clearer status message while waiting for the next closed 3-minute candle.
