from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import aiohttp


def interval_to_milliseconds(interval: str) -> int:
    units = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}
    if len(interval) < 2 or interval[-1] not in units:
        raise ValueError(f"Unsupported interval: {interval}")
    return int(interval[:-1]) * units[interval[-1]]


class BinanceMarketDataV10:
    """Futures aggregate-trade stream plus completed-bar integrity recovery."""

    integrity_version = "SPLIT_WS_COMPLETED_BAR_WATCHDOG_V3"

    rest_url = "https://fapi.binance.com/fapi/v1/klines"
    aggregate_trade_url = "https://fapi.binance.com/fapi/v1/aggTrades"
    premium_index_url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    book_ticker_url = "https://fapi.binance.com/fapi/v1/ticker/bookTicker"
    ticker_price_url = "https://fapi.binance.com/fapi/v2/ticker/price"
    # Binance retired the legacy USD-M `/stream` route for regular market
    # channels in April 2026.  Book data and regular market data now belong on
    # separate routed endpoints.
    market_stream_base = "wss://fstream.binance.com/market/stream?streams="
    public_stream_base = "wss://fstream.binance.com/public/stream?streams="

    def __init__(self, symbol: str = "XAUUSDT", interval: str = "3m") -> None:
        self.symbol = symbol.upper()
        self.stream_symbol = self.symbol.lower()
        self.interval = interval
        self.interval_ms = interval_to_milliseconds(interval)
        self.running = False
        self.last_candle_time: int | None = None
        self._session: aiohttp.ClientSession | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._public_websocket: aiohttp.ClientWebSocketResponse | None = None
        self._funding_schedule: tuple[int, float] | None = None
        self._applied_funding_times: set[int] = set()
        self._last_aggregate_trade_id: int | None = None

        # Per-channel liveness is deliberately independent. A busy book stream
        # must never hide a silent kline or aggregate-trade channel.
        self.channel_stale_seconds = 10.0
        self.integrity_poll_seconds = 2.0
        self.rest_execution_freshness_ms = 5_000
        self._last_kline_frame_monotonic: float | None = None
        self._last_agg_trade_frame_monotonic: float | None = None
        self._last_book_frame_monotonic: float | None = None
        self._kline_degraded = False
        self._agg_trade_degraded = False
        self._book_degraded = False
        self._market_socket_connected = False
        self._public_socket_connected = False
        self._rest_candles_recovered = 0
        self._rest_trades_recovered = 0
        # Tracks one status notice per missing completed-bar boundary.  This is
        # separate from kline-frame liveness because preview frames can remain
        # healthy even when the final closed-bar event is never delivered.
        self._last_completion_gap_notice_open: int | None = None
        self._candle_lock: asyncio.Lock | None = None
        self._trade_lock: asyncio.Lock | None = None

        self.candle_callback: Callable[..., Any] | None = None
        self.price_callback: Callable[..., Any] | None = None
        self.history_callback: Callable[..., Any] | None = None
        self.history_complete_callback: Callable[..., Any] | None = None
        self.preview_callback: Callable[..., Any] | None = None
        self.funding_callback: Callable[..., Any] | None = None
        self.trade_callback: Callable[..., Any] | None = None
        self.book_callback: Callable[..., Any] | None = None
        self.display_price_callback: Callable[..., Any] | None = None
        self.status_callback: Callable[..., Any] | None = None

    async def _invoke(self, callback: Callable[..., Any] | None, *args: Any) -> None:
        if callback is None:
            return
        result = callback(*args)
        if asyncio.iscoroutine(result):
            await result

    async def _status(self, message: str) -> None:
        # Feed state must also be visible in the terminal. Qt status labels are
        # useful, but they made the original silent-channel failure look like an
        # idle bot when the database was actually receiving zero decisions.
        print(f"[FEED] {message}", flush=True)
        try:
            await self._invoke(self.status_callback, message)
        except Exception:
            pass

    def _expected_latest_closed_open_time(
        self,
        *,
        now_ms: int | None = None,
    ) -> int:
        """Return the open-time of the 3m bar that must already be closed."""
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        current_open = (int(now_ms) // self.interval_ms) * self.interval_ms
        return current_open - self.interval_ms

    @staticmethod
    def _closed_candle(row: list[Any]) -> dict[str, Any]:
        return {
            "time": int(row[0]),
            "close_time": int(row[6]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "closed": True,
            "replayed": True,
        }

    async def _fetch_klines(
        self,
        session: aiohttp.ClientSession,
        *,
        limit: int = 200,
        start_time: int | None = None,
    ) -> list[list[Any]]:
        params: dict[str, Any] = {
            "symbol": self.symbol,
            "interval": self.interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = int(start_time)
        async with session.get(self.rest_url, params=params) as response:
            response.raise_for_status()
            payload = await response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected kline response: {payload!r}")
        return payload

    async def _fetch_aggregate_trades(
        self,
        session: aiohttp.ClientSession,
        *,
        from_id: int | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": self.symbol, "limit": int(limit)}
        if from_id is not None:
            params["fromId"] = int(from_id)
        async with session.get(self.aggregate_trade_url, params=params) as response:
            response.raise_for_status()
            payload = await response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected aggregate-trade response: {payload!r}")
        return payload

    async def _initialize_aggregate_trade_cursor(
        self,
        session: aiohttp.ClientSession,
    ) -> None:
        if self._trade_lock is None:
            self._trade_lock = asyncio.Lock()
        async with self._trade_lock:
            if self._last_aggregate_trade_id is not None:
                return
            rows = await self._fetch_aggregate_trades(session, limit=1)
            if not rows:
                raise RuntimeError(
                    "No aggregate trades available for cursor initialization"
                )
            latest = rows[-1]
            self._last_aggregate_trade_id = int(latest["a"])
            # Bootstrap establishes the cursor and gives diagnostics one recent
            # print. It is never an execution observation because it may predate
            # startup.
            await self._invoke(
                self.trade_callback,
                {
                    "aggregate_id": int(latest["a"]),
                    "price": float(latest["p"]),
                    "quantity": float(latest["q"]),
                    "buyer_is_maker": bool(latest["m"]),
                    "event_time": int(latest["T"]),
                    "source": "REST_AGGTRADE_BOOTSTRAP",
                    "entry_eligible": False,
                },
            )

    def channel_health_snapshot(self) -> dict[str, Any]:
        """Return source/channel health for diagnostics without affecting trades."""
        now = time.monotonic()

        def age(last_seen: float | None) -> float | None:
            return None if last_seen is None else max(0.0, now - last_seen)

        return {
            "feed_integrity_version": self.integrity_version,
            "market_ws_connected": self._market_socket_connected,
            "public_ws_connected": self._public_socket_connected,
            "kline_ws_age_s": age(self._last_kline_frame_monotonic),
            "agg_trade_ws_age_s": age(self._last_agg_trade_frame_monotonic),
            "book_ws_age_s": age(self._last_book_frame_monotonic),
            "kline_rest_degraded": self._kline_degraded,
            "agg_trade_rest_degraded": self._agg_trade_degraded,
            "book_rest_degraded": self._book_degraded,
            "rest_candles_recovered": self._rest_candles_recovered,
            "rest_trades_recovered": self._rest_trades_recovered,
        }

    async def _bootstrap_history(self, session: aiohttp.ClientSession) -> None:
        await self._status("Loading completed 3m history...")
        rows = await self._fetch_klines(session, limit=200)
        now_ms = int(time.time() * 1000)
        loaded = 0
        for row in rows:
            if int(row[6]) >= now_ms:
                continue
            candle = self._closed_candle(row)
            await self._invoke(self.history_callback, candle)
            self.last_candle_time = int(candle["time"])
            loaded += 1
        if loaded == 0:
            raise RuntimeError("No completed historical candles were loaded")
        await self._invoke(self.history_complete_callback)
        await self._status(
            "History ready: "
            f"{loaded} completed candle(s); latest_open={self.last_candle_time}"
        )

    async def _emit_candle_decision_locked(
        self,
        candle: dict[str, Any],
    ) -> bool:
        """Emit one completed decision candle while the caller holds the lock."""
        open_time = int(candle["time"])
        if self.last_candle_time is not None and open_time <= self.last_candle_time:
            return False
        await self._invoke(self.candle_callback, candle)
        self.last_candle_time = open_time
        return True

    async def _replay_missing_locked(
        self,
        session: aiohttp.ClientSession,
        before_open_time: int | None = None,
    ) -> int:
        if self.last_candle_time is None:
            return 0

        cursor = self.last_candle_time + self.interval_ms
        replayed = 0
        while self.running:
            now_ms = int(time.time() * 1000)
            rows = await self._fetch_klines(session, limit=1_000, start_time=cursor)
            eligible = []
            for row in rows:
                open_time = int(row[0])
                close_time = int(row[6])
                if close_time >= now_ms:
                    continue
                if before_open_time is not None and open_time >= before_open_time:
                    continue
                if open_time <= int(self.last_candle_time):
                    continue
                eligible.append(row)

            if not eligible:
                break

            for row in eligible:
                candle = self._closed_candle(row)
                candle["recovered"] = True
                candle["source"] = "REST_KLINE_RECOVERY"
                emitted = await self._emit_candle_decision_locked(candle)
                if emitted:
                    replayed += 1
                cursor = int(row[0]) + self.interval_ms

            if len(rows) < 1_000:
                break
            if before_open_time is not None and cursor >= before_open_time:
                break
        return replayed

    async def _replay_missing(
        self,
        session: aiohttp.ClientSession,
        before_open_time: int | None = None,
    ) -> int:
        if self._candle_lock is None:
            self._candle_lock = asyncio.Lock()
        async with self._candle_lock:
            return await self._replay_missing_locked(session, before_open_time)

    @staticmethod
    def _rest_trade_is_execution_fresh(
        event_time_ms: int,
        freshness_ms: int,
        *,
        now_ms: int | None = None,
    ) -> bool:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        age_ms = int(now_ms) - int(event_time_ms)
        return -1_000 <= age_ms <= int(freshness_ms)

    async def _emit_aggregate_trade(
        self,
        aggregate: dict[str, Any],
        source: str,
        *,
        execution_eligible: bool,
    ) -> bool:
        if self._trade_lock is None:
            self._trade_lock = asyncio.Lock()
        aggregate_id = int(aggregate["a"])
        async with self._trade_lock:
            if (
                self._last_aggregate_trade_id is not None
                and aggregate_id <= self._last_aggregate_trade_id
            ):
                return False

            trade = {
                "aggregate_id": aggregate_id,
                "price": float(aggregate["p"]),
                "quantity": float(aggregate["q"]),
                "buyer_is_maker": bool(aggregate["m"]),
                "event_time": int(aggregate["T"]),
                "source": str(source),
                # Consumers must distinguish forward entry eligibility from
                # historical path/exit eligibility. Replayed prints may never
                # open a position, but they still describe what happened to an
                # already-open position during a transient feed interruption.
                "entry_eligible": bool(execution_eligible),
            }
            await self._invoke(self.trade_callback, trade)
            if execution_eligible:
                await self._invoke(
                    self.price_callback,
                    float(aggregate["p"]),
                    int(aggregate["T"]),
                    str(source),
                )
            self._last_aggregate_trade_id = aggregate_id
            return True

    @staticmethod
    def _stream_candle(kline: dict[str, Any]) -> dict[str, Any]:
        return {
            "time": int(kline["t"]),
            "close_time": int(kline["T"]),
            "open": float(kline["o"]),
            "high": float(kline["h"]),
            "low": float(kline["l"]),
            "close": float(kline["c"]),
            "volume": float(kline["v"]),
            "closed": bool(kline["x"]),
            "replayed": False,
        }

    async def _handle_kline(
        self,
        session: aiohttp.ClientSession,
        payload: dict[str, Any],
    ) -> None:
        loop_time = asyncio.get_running_loop().time()
        self._last_kline_frame_monotonic = loop_time
        if self._kline_degraded:
            self._kline_degraded = False
            await self._status("Kline WebSocket channel recovered")

        candle = self._stream_candle(payload["k"])
        candle["source"] = "WS_KLINE"
        await self._invoke(self.preview_callback, candle)
        if not candle["closed"]:
            return

        if self._candle_lock is None:
            self._candle_lock = asyncio.Lock()
        async with self._candle_lock:
            open_time = int(candle["time"])
            if self.last_candle_time is not None and open_time <= self.last_candle_time:
                return

            if (
                self.last_candle_time is not None
                and open_time > self.last_candle_time + self.interval_ms
            ):
                count = await self._replay_missing_locked(
                    session,
                    before_open_time=open_time,
                )
                if count:
                    await self._status(
                        f"Recovered {count} missing candle(s); stale entries suppressed"
                    )

            await self._emit_candle_decision_locked(candle)

    async def _emit_closed_candle_from_row(
        self,
        row: list[Any],
        *,
        source: str = "REST_KLINE_RECOVERY",
    ) -> bool:
        candle = self._closed_candle(row)
        candle["recovered"] = True
        candle["source"] = str(source)
        if self._candle_lock is None:
            self._candle_lock = asyncio.Lock()
        async with self._candle_lock:
            return await self._emit_candle_decision_locked(candle)

    async def _handle_mark_price(self, payload: dict[str, Any]) -> None:
        event_time = int(payload["E"])
        next_funding_time = int(payload["T"])
        funding_rate = float(payload["r"])
        mark_price = float(payload["p"])

        previous = self._funding_schedule
        if previous is not None:
            scheduled_time, scheduled_rate = previous
            if (
                event_time >= scheduled_time
                and scheduled_time not in self._applied_funding_times
            ):
                await self._invoke(
                    self.funding_callback,
                    scheduled_time,
                    scheduled_rate,
                    mark_price,
                )
                self._applied_funding_times.add(scheduled_time)

        self._funding_schedule = (next_funding_time, funding_rate)

    async def _poll_premium_index(self, session: aiohttp.ClientSession) -> None:
        params = {"symbol": self.symbol}
        async with session.get(self.premium_index_url, params=params) as response:
            response.raise_for_status()
            payload = await response.json()
        event_time = int(payload["time"])
        next_funding_time = int(payload["nextFundingTime"])
        funding_rate = float(payload["lastFundingRate"])
        mark_price = float(payload["markPrice"])
        await self._handle_mark_price(
            {
                "E": event_time,
                "T": next_funding_time,
                "r": funding_rate,
                "p": mark_price,
            }
        )

    async def _poll_book_ticker(self, session: aiohttp.ClientSession) -> None:
        params = {"symbol": self.symbol}
        async with session.get(self.book_ticker_url, params=params) as response:
            response.raise_for_status()
            payload = await response.json()
        await self._invoke(
            self.book_callback,
            {
                "bid": float(payload["bidPrice"]),
                "bid_quantity": float(payload["bidQty"]),
                "ask": float(payload["askPrice"]),
                "ask_quantity": float(payload["askQty"]),
                "event_time": int(payload.get("time", time.time() * 1000)),
                "source": "REST_BOOK_TICKER",
            },
        )

    async def _display_last_price_loop(
        self,
        session: aiohttp.ClientSession,
    ) -> None:
        """Sync the GUI to Binance Futures Last Price without trading on it."""
        while self.running:
            try:
                params = {"symbol": self.symbol}
                async with session.get(
                    self.ticker_price_url,
                    params=params,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json()
                await self._invoke(
                    self.display_price_callback,
                    float(payload["price"]),
                    int(payload["time"]),
                    "REST_BINANCE_LAST_PRICE",
                )
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                # BookTicker remains the visual fallback. Execution and candle
                # decisions are intentionally unaffected by display failures.
                await asyncio.sleep(2.0)

    async def _fetch_unseen_aggregate_trades(
        self,
        session: aiohttp.ClientSession,
    ) -> list[dict[str, Any]]:
        if self._last_aggregate_trade_id is None:
            await self._initialize_aggregate_trade_cursor(session)
            return []

        unseen: list[dict[str, Any]] = []
        next_id = self._last_aggregate_trade_id + 1
        while self.running:
            rows = await self._fetch_aggregate_trades(
                session,
                from_id=next_id,
                limit=1_000,
            )
            rows = [row for row in rows if int(row["a"]) >= next_id]
            if not rows:
                break
            unseen.extend(rows)
            last_id = int(rows[-1]["a"])
            next_id = last_id + 1
            if len(rows) < 1_000:
                break
        return unseen

    async def _rest_candle_integrity_sync(
        self,
        session: aiohttp.ClientSession,
    ) -> int:
        count = await self._replay_missing(session)
        self._rest_candles_recovered += count

        # Keep the forming candle visually useful while the kline WS is degraded.
        rows = await self._fetch_klines(session, limit=2)
        now_ms = int(time.time() * 1000)
        forming = [row for row in rows if int(row[6]) >= now_ms]
        if forming:
            preview = self._closed_candle(forming[-1])
            preview["closed"] = False
            preview["replayed"] = False
            preview["recovered"] = True
            preview["source"] = "REST_KLINE_PREVIEW"
            await self._invoke(self.preview_callback, preview)
        return count

    async def _rest_aggregate_trade_integrity_sync(
        self,
        session: aiohttp.ClientSession,
    ) -> tuple[int, int]:
        await self._initialize_aggregate_trade_cursor(session)
        rows = await self._fetch_unseen_aggregate_trades(session)
        rows.sort(key=lambda row: (int(row["T"]), int(row["a"])))
        now_ms = int(time.time() * 1000)
        emitted = 0
        execution_fresh = 0
        for aggregate in rows:
            fresh = self._rest_trade_is_execution_fresh(
                int(aggregate["T"]),
                self.rest_execution_freshness_ms,
                now_ms=now_ms,
            )
            if await self._emit_aggregate_trade(
                aggregate,
                "REST_AGGTRADE_REPLAY",
                execution_eligible=fresh,
            ):
                emitted += 1
                if fresh:
                    execution_fresh += 1
        self._rest_trades_recovered += emitted
        return emitted, execution_fresh

    async def _integrity_loop(
        self,
        session: aiohttp.ClientSession,
    ) -> None:
        """Independently verify kline/aggTrade liveness even if book frames flow."""
        loop = asyncio.get_running_loop()
        next_funding_poll = 0.0
        while self.running:
            now = loop.time()
            try:
                # Bring aggregate trades current before producing a recovered
                # candle decision. The diagnostic snapshot then has the complete
                # causal order-flow window through that candle's close; its
                # as-of filter still excludes later prints.
                agg_age = (
                    float("inf")
                    if self._last_agg_trade_frame_monotonic is None
                    else now - self._last_agg_trade_frame_monotonic
                )
                if agg_age > self.channel_stale_seconds:
                    if not self._agg_trade_degraded:
                        self._agg_trade_degraded = True
                        await self._status(
                            "DEGRADED FEED: aggTrade WS silent; REST trade integrity active"
                        )
                    recovered, fresh = await self._rest_aggregate_trade_integrity_sync(
                        session
                    )
                    if recovered:
                        await self._status(
                            "REST integrity recovered "
                            f"{recovered} aggregate trade(s); {fresh} fresh for entry"
                        )

                kline_age = (
                    float("inf")
                    if self._last_kline_frame_monotonic is None
                    else now - self._last_kline_frame_monotonic
                )

                # Critical invariant: verify the COMPLETED BAR itself, not just
                # arrival of kline preview frames. A stream can keep sending an
                # open/forming candle while the x=True close frame is missed.
                expected_closed_open = self._expected_latest_closed_open_time()
                completed_bar_missing = (
                    self.last_candle_time is None
                    or int(self.last_candle_time) < int(expected_closed_open)
                )

                if completed_bar_missing:
                    if self._last_completion_gap_notice_open != expected_closed_open:
                        self._last_completion_gap_notice_open = expected_closed_open
                        await self._status(
                            "COMPLETED BAR MISSING: "
                            f"expected_open={expected_closed_open} "
                            f"last_delivered={self.last_candle_time}; "
                            "REST candle integrity active"
                        )
                    recovered = await self._rest_candle_integrity_sync(session)
                    if recovered:
                        await self._status(
                            f"REST integrity recovered {recovered} completed candle(s)"
                        )
                    if (
                        self.last_candle_time is not None
                        and int(self.last_candle_time) >= int(expected_closed_open)
                    ):
                        await self._status(
                            "Completed-bar integrity restored: "
                            f"latest_open={self.last_candle_time}"
                        )
                        self._last_completion_gap_notice_open = None
                elif kline_age > self.channel_stale_seconds:
                    # A stale preview channel still gets REST preview support,
                    # even when completed-bar decisions are currently caught up.
                    if not self._kline_degraded:
                        self._kline_degraded = True
                        await self._status(
                            "DEGRADED FEED: kline WS silent; REST candle integrity active"
                    )
                    await self._rest_candle_integrity_sync(session)

                book_age = (
                    float("inf")
                    if self._last_book_frame_monotonic is None
                    else now - self._last_book_frame_monotonic
                )
                if book_age > self.channel_stale_seconds:
                    if not self._book_degraded:
                        self._book_degraded = True
                        await self._status(
                            "DEGRADED FEED: bookTicker WS silent; REST book fallback active"
                        )
                    await self._poll_book_ticker(session)

                if now >= next_funding_poll:
                    await self._poll_premium_index(session)
                    next_funding_poll = now + 30.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._status(
                    "REST integrity check failed "
                    f"({type(exc).__name__}); will retry"
                )

            await asyncio.sleep(self.integrity_poll_seconds)

    async def _rest_aggregate_trade_fallback(
        self,
        session: aiohttp.ClientSession,
        duration_seconds: float = 60.0,
    ) -> None:
        """Compatibility wrapper around the independent safe REST integrity path."""
        await self._status(
            "DEGRADED FEED: REST integrity active; retrying WebSocket separately"
        )
        deadline = asyncio.get_running_loop().time() + duration_seconds
        while self.running and asyncio.get_running_loop().time() < deadline:
            await self._rest_candle_integrity_sync(session)
            await self._rest_aggregate_trade_integrity_sync(session)
            await self._poll_premium_index(session)
            await self._poll_book_ticker(session)
            await asyncio.sleep(self.integrity_poll_seconds)

    async def _consume_market_stream(self, session: aiohttp.ClientSession) -> None:
        streams = "/".join(
            (
                f"{self.stream_symbol}@aggTrade",
                f"{self.stream_symbol}@kline_{self.interval}",
                f"{self.stream_symbol}@markPrice@1s",
            )
        )
        url = self.market_stream_base + streams
        await self._initialize_aggregate_trade_cursor(session)
        async with session.ws_connect(
            url,
            heartbeat=20,
            autoping=True,
            receive_timeout=60,
        ) as websocket:
            self._websocket = websocket
            self._market_socket_connected = True
            connected_at = asyncio.get_running_loop().time()
            self._last_kline_frame_monotonic = connected_at
            self._last_agg_trade_frame_monotonic = connected_at
            replayed = await self._replay_missing(session)
            if replayed:
                await self._status(
                    f"Reconnected; recovered {replayed} candle decision(s); stale entries suppressed"
                )
            else:
                await self._status(
                    "Binance /market WebSocket connected; aggTrade/kline/mark active"
                )

            try:
                while self.running:
                    try:
                        message = await asyncio.wait_for(
                            websocket.receive(), timeout=15.0
                        )
                    except TimeoutError as exc:
                        raise RuntimeError(
                            "Market WebSocket connected but delivered no frames"
                        ) from exc
                    if not self.running:
                        break
                    if message.type == aiohttp.WSMsgType.TEXT:
                        envelope = message.json()
                        payload = envelope.get("data", envelope)
                        event = payload.get("e")
                        if event == "aggTrade":
                            self._last_agg_trade_frame_monotonic = (
                                asyncio.get_running_loop().time()
                            )
                            if self._agg_trade_degraded:
                                self._agg_trade_degraded = False
                                await self._status(
                                    "Aggregate-trade WebSocket channel recovered"
                                )
                            fresh = self._rest_trade_is_execution_fresh(
                                int(payload["T"]),
                                self.rest_execution_freshness_ms,
                            )
                            await self._emit_aggregate_trade(
                                payload,
                                "WS_AGGTRADE",
                                execution_eligible=fresh,
                            )
                        elif event == "kline":
                            await self._handle_kline(session, payload)
                        elif event == "markPriceUpdate":
                            await self._handle_mark_price(payload)
                    elif message.type in {
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.ERROR,
                    }:
                        raise RuntimeError("Market WebSocket closed")
            finally:
                self._market_socket_connected = False
                self._websocket = None

    async def _consume_public_stream(self, session: aiohttp.ClientSession) -> None:
        url = self.public_stream_base + f"{self.stream_symbol}@bookTicker"
        async with session.ws_connect(
            url,
            heartbeat=20,
            autoping=True,
            receive_timeout=60,
        ) as websocket:
            self._public_websocket = websocket
            self._public_socket_connected = True
            self._last_book_frame_monotonic = asyncio.get_running_loop().time()
            await self._status("Binance /public WebSocket connected; bookTicker active")
            try:
                while self.running:
                    try:
                        message = await asyncio.wait_for(
                            websocket.receive(), timeout=15.0
                        )
                    except TimeoutError as exc:
                        raise RuntimeError(
                            "Public WebSocket connected but delivered no frames"
                        ) from exc
                    if not self.running:
                        break
                    if message.type == aiohttp.WSMsgType.TEXT:
                        envelope = message.json()
                        payload = envelope.get("data", envelope)
                        if payload.get("e") != "bookTicker":
                            continue
                        self._last_book_frame_monotonic = (
                            asyncio.get_running_loop().time()
                        )
                        if self._book_degraded:
                            self._book_degraded = False
                            await self._status("BookTicker WebSocket channel recovered")
                        await self._invoke(
                            self.book_callback,
                            {
                                "bid": float(payload["b"]),
                                "bid_quantity": float(payload["B"]),
                                "ask": float(payload["a"]),
                                "ask_quantity": float(payload["A"]),
                                "event_time": int(payload["E"]),
                                "source": "WS_BOOK_TICKER",
                            },
                        )
                    elif message.type in {
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.ERROR,
                    }:
                        raise RuntimeError("Public WebSocket closed")
            finally:
                self._public_socket_connected = False
                self._public_websocket = None

    async def _consume_stream(self, session: aiohttp.ClientSession) -> None:
        # If either routed socket fails, TaskGroup cancels its sibling and the
        # existing reconnect loop restarts both cleanly. REST integrity remains
        # independent throughout the reconnect.
        async with asyncio.TaskGroup() as group:
            group.create_task(self._consume_market_stream(session))
            group.create_task(self._consume_public_stream(session))

    async def start(
        self,
        candle_callback: Callable[..., Any] | None = None,
        price_callback: Callable[..., Any] | None = None,
        history_callback: Callable[..., Any] | None = None,
        history_complete_callback: Callable[..., Any] | None = None,
        preview_callback: Callable[..., Any] | None = None,
        funding_callback: Callable[..., Any] | None = None,
        trade_callback: Callable[..., Any] | None = None,
        book_callback: Callable[..., Any] | None = None,
        display_price_callback: Callable[..., Any] | None = None,
        status_callback: Callable[..., Any] | None = None,
    ) -> None:
        self.candle_callback = candle_callback
        self.price_callback = price_callback
        self.history_callback = history_callback
        self.history_complete_callback = history_complete_callback
        self.preview_callback = preview_callback
        self.funding_callback = funding_callback
        self.trade_callback = trade_callback
        self.book_callback = book_callback
        self.display_price_callback = display_price_callback
        self.status_callback = status_callback
        self.running = True
        # Locks are created on the actual asyncio worker loop, not the Qt thread.
        self._candle_lock = asyncio.Lock()
        self._trade_lock = asyncio.Lock()
        # Give the two sockets their normal connection window before declaring
        # a channel degraded. Without this seed the watchdog emits false alarms
        # during the first event-loop tick of every clean startup.
        startup_time = asyncio.get_running_loop().time()
        self._last_kline_frame_monotonic = startup_time
        self._last_agg_trade_frame_monotonic = startup_time
        self._last_book_frame_monotonic = startup_time

        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=10,
            sock_connect=10,
            sock_read=None,
        )
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                self._session = session
                await self._bootstrap_history(session)
                display_task = asyncio.create_task(
                    self._display_last_price_loop(session)
                )
                integrity_task = asyncio.create_task(
                    self._integrity_loop(session)
                )
                try:
                    backoff = 1
                    while self.running:
                        try:
                            await self._consume_stream(session)
                            backoff = 1
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            await self._status(
                                "Market stream interrupted "
                                f"({type(exc).__name__}); reconnecting while REST integrity stays active"
                            )
                            if self.running:
                                await asyncio.sleep(backoff)
                                backoff = min(backoff * 2, 30)
                finally:
                    display_task.cancel()
                    integrity_task.cancel()
                    await asyncio.gather(
                        display_task,
                        integrity_task,
                        return_exceptions=True,
                    )
        finally:
            self._session = None

    async def stop(self) -> None:
        self.running = False
        if self._websocket is not None and not self._websocket.closed:
            await self._websocket.close()
        if (
            self._public_websocket is not None
            and not self._public_websocket.closed
        ):
            await self._public_websocket.close()
