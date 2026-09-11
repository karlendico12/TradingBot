import asyncio
import aiohttp

class BinanceKlineFeed:

    def __init__(self,symbol="xauusdt",interval="3m"):

        self.symbol=symbol.lower()
        self.interval=interval
        self.callback=None

    @property
    def url(self):

        return (
            f"wss://fstream.binance.com/ws/"
            f"{self.symbol}@kline_{self.interval}"
        )

    async def start(self):

        while True:

            try:

                async with aiohttp.ClientSession() as session:

                    async with session.ws_connect(self.url) as ws:

                        async for msg in ws:

                            if msg.type==aiohttp.WSMsgType.TEXT:

                                k=msg.json()["k"]

                                candle={
                                    "time":k["t"],
                                    "open":float(k["o"]),
                                    "high":float(k["h"]),
                                    "low":float(k["l"]),
                                    "close":float(k["c"]),
                                    "volume":float(k["v"]),
                                    "closed":k["x"]
                                }

                                if self.callback:
                                    self.callback(candle)

            except Exception as e:

                print("Reconnect:",e)

                await asyncio.sleep(3)