import asyncio
import aiohttp
import time


class WebSocketManager:

    def __init__(self, symbol="xauusdt", interval="3m"):

        self.symbol = symbol.upper()
        self.interval = interval

        # ==================================================
        # CALLBACKS
        # ==================================================

        self.kline_callback = None
        self.history_callback = None
        self.history_complete_callback = None
        self.price_callback = None
        self.status_callback = None

        # ==================================================
        # STATE
        # ==================================================

        self.running = True

        self.last_candle_time = None
        self.last_price = None

        self.initialized = False

    # ==========================================================
    # SET CALLBACKS
    # ==========================================================

    def set_candle_callback(self, callback):

        self.kline_callback = callback

    def set_history_callback(self, callback):

        self.history_callback = callback

    def set_history_complete_callback(self, callback):

        self.history_complete_callback = callback

    def set_price_callback(self, callback):

        self.price_callback = callback

    def set_status_callback(self, callback):

        self.status_callback = callback

    # ==========================================================
    # START
    # ==========================================================

    async def start(
        self,
        candle_callback=None,
        price_callback=None,
        history_callback=None,
        history_complete_callback=None,
    ):

        # ==================================================
        # ACCEPT CALLBACKS FROM TRADINGBOT
        # ==================================================

        # Allow the manager to be started again after stop().
        self.running = True

        if candle_callback is not None:

            self.kline_callback = candle_callback

        if price_callback is not None:

            self.price_callback = price_callback

        if history_callback is not None:

            self.history_callback = history_callback

        if history_complete_callback is not None:

            self.history_complete_callback = history_complete_callback

        # ==================================================
        # BINANCE REST ENDPOINT
        # ==================================================

        url = (
            "https://fapi.binance.com/"
            "fapi/v1/klines"
        )

        print("=" * 60)

        print(
            "BINANCE REST MARKET DATA"
        )

        print(
            "Symbol:",
            self.symbol
        )

        print(
            "Interval:",
            self.interval
        )

        print("=" * 60, flush=True)

        # ==================================================
        # STATUS
        # ==================================================

        if self.status_callback:

            try:

                self.status_callback(
                    "Connecting to Binance..."
                )

            except Exception:

                pass

        timeout = aiohttp.ClientTimeout(
            total=10
        )

        try:

            async with aiohttp.ClientSession(
                timeout=timeout
            ) as session:

                # ==========================================
                # LOAD HISTORY
                # ==========================================

                await self.load_historical_candles(
                    session,
                    url
                )

                # ==========================================
                # CONNECTION SUCCESS
                # ==========================================

                if self.status_callback:

                    try:

                        self.status_callback(
                            "Connected to Binance"
                        )

                    except Exception:

                        pass

                print(
                    "[REST] Market data connection ready",
                    flush=True
                )

                # ==========================================
                # CONTINUOUS MARKET DATA LOOP
                # ==========================================

                while self.running:

                    try:

                        params = {
                            "symbol": self.symbol,
                            "interval": self.interval,
                            "limit": 10,
                        }

                        async with session.get(
                            url,
                            params=params
                        ) as response:

                            if response.status != 200:

                                text = await response.text()

                                print(
                                    "[REST ERROR]",
                                    response.status,
                                    text,
                                    flush=True
                                )

                                if self.status_callback:

                                    try:

                                        self.status_callback(
                                            "Binance API error"
                                        )

                                    except Exception:

                                        pass

                                await asyncio.sleep(5)

                                continue

                            data = await response.json()

                            if (
                                not data
                                or len(data) < 2
                            ):

                                print(
                                    "[REST] Not enough "
                                    "candle data",
                                    flush=True
                                )

                                await asyncio.sleep(5)

                                continue

                            # ==================================
                            # CURRENT FORMING CANDLE
                            # ==================================

                            current = data[-1]

                            current_price = float(
                                current[4]
                            )

                            self.last_price = (
                                current_price
                            )

                            # ==================================
                            # SEND LIVE PRICE
                            # ==================================

                            if self.price_callback:

                                try:

                                    result = (
                                        self.price_callback(
                                            current_price
                                        )
                                    )

                                    # Supports async callback
                                    if asyncio.iscoroutine(
                                        result
                                    ):

                                        await result

                                except Exception:

                                    print(
                                        "[PRICE CALLBACK ERROR]",
                                        flush=True
                                    )

                            # ==================================
                            # PRINT PRICE
                            # ==================================

                            print(
                                f"[PRICE] {self.symbol}: "
                                f"{current_price:.2f}",
                                flush=True
                            )

                            # ==================================
                            # LAST CLOSED CANDLE
                            # ==================================

                            latest = data[-2]

                            candle_open_time = int(
                                latest[0]
                            )

                            candle_close_time = int(
                                latest[6]
                            )

                            candle = {
                                "time": candle_open_time,
                                "open": float(latest[1]),
                                "high": float(latest[2]),
                                "low": float(latest[3]),
                                "close": float(latest[4]),
                                "volume": float(latest[5]),
                                "closed": True,
                            }

                            # ==================================
                            # VERIFY CANDLE CLOSED
                            # ==================================

                            current_time = int(
                                time.time() * 1000
                            )

                            if (
                                current_time
                                <= candle_close_time
                            ):

                                print(
                                    "[CANDLE] Last candle "
                                    "not confirmed closed",
                                    flush=True
                                )

                            else:

                                # ==================================
                                # ONLY SEND NEW CLOSED CANDLE
                                # ==================================

                                if (
                                    self.last_candle_time
                                    != candle_open_time
                                ):

                                    self.last_candle_time = (
                                        candle_open_time
                                    )

                                    print(
                                        "[CANDLE CLOSED]",
                                        candle,
                                        flush=True
                                    )

                                    if self.kline_callback:

                                        try:

                                            result = (
                                                self.kline_callback(
                                                    candle
                                                )
                                            )

                                            if asyncio.iscoroutine(
                                                result
                                            ):

                                                await result

                                        except Exception:

                                            print(
                                                "[CANDLE CALLBACK ERROR]",
                                                flush=True
                                            )

                                else:

                                    print(
                                        "[CANDLE] "
                                        "No new closed candle",
                                        flush=True
                                    )

                        # ==================================
                        # POLLING INTERVAL
                        # ==================================

                        await asyncio.sleep(5)

                    except asyncio.CancelledError:

                        print(
                            "[REST] Task cancelled",
                            flush=True
                        )

                        break

                    except Exception as e:

                        print(
                            "[REST ERROR]",
                            repr(e),
                            flush=True
                        )

                        await asyncio.sleep(5)

        except asyncio.CancelledError:

            print(
                "[REST] Market data task cancelled",
                flush=True
            )

        except Exception as e:

            print(
                "[REST FATAL ERROR]",
                repr(e),
                flush=True
            )

            if self.status_callback:

                try:

                    self.status_callback(
                        "Binance connection failed"
                    )

                except Exception:

                    pass

        finally:

            print(
                "[REST] Market data stopped",
                flush=True
            )

    # ==========================================================
    # LOAD HISTORICAL CANDLES
    # ==========================================================

    async def load_historical_candles(
        self,
        session,
        url
    ):

        print(
            "[HISTORY] Loading historical candles...",
            flush=True
        )

        params = {
            "symbol": self.symbol,
            "interval": self.interval,
            "limit": 200,
        }

        try:

            async with session.get(
                url,
                params=params
            ) as response:

                if response.status != 200:

                    text = await response.text()

                    print(
                        "[HISTORY ERROR]",
                        response.status,
                        text,
                        flush=True
                    )

                    return

                data = await response.json()

                if not data:

                    print(
                        "[HISTORY] No historical data",
                        flush=True
                    )

                    return

                current_time = int(
                    time.time() * 1000
                )

                loaded = 0

                # ==========================================
                # PROCESS HISTORICAL CANDLES
                # ==========================================

                for item in data:

                    candle_open_time = int(
                        item[0]
                    )

                    candle_close_time = int(
                        item[6]
                    )

                    # Skip forming candle
                    if (
                        current_time
                        <= candle_close_time
                    ):

                        continue

                    candle = {
                        "time": candle_open_time,
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": float(item[5]),
                        "closed": True,
                    }

                    # Historical candles warm up indicators only.
                    # They must not execute the live trading callback,
                    # otherwise the bot can create fake startup trades.
                    callback = self.history_callback

                    if callback:

                        try:

                            result = callback(candle)

                            if asyncio.iscoroutine(result):

                                await result

                        except Exception:

                            print(
                                "[HISTORY CALLBACK ERROR]",
                                flush=True
                            )

                    self.last_candle_time = (
                        candle_open_time
                    )

                    loaded += 1

                self.initialized = True

                print(
                    f"[HISTORY] Loaded "
                    f"{loaded} closed candles",
                    flush=True
                )

                print(
                    "[HISTORY] Signal engine ready",
                    flush=True
                )

                # Notify the bot once after the indicator warm-up is complete.
                # This lets the GUI render historical candles immediately
                # without treating those candles as live trading events.
                if self.history_complete_callback:

                    try:
                        result = self.history_complete_callback()

                        if asyncio.iscoroutine(result):
                            await result

                    except Exception:
                        print(
                            "[HISTORY COMPLETE CALLBACK ERROR]",
                            flush=True
                        )

        except Exception as e:

            print(
                "[HISTORY ERROR]",
                repr(e),
                flush=True
            )

    # ==========================================================
    # STOP
    # ==========================================================

    async def stop(self):

        self.running = False

        print(
            "[REST] Stop requested",
            flush=True
        )