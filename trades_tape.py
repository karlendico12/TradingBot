import asyncio
import aiohttp

class TradesFeed:

    def __init__(self, symbol="xauusdt"):
        self.symbol = symbol.lower()
        self.callback = None

    @property
    def url(self):
        return f"wss://fstream.binance.com/ws/{self.symbol}@trade"

    async def start(self):

        while True:

            try:

                async with aiohttp.ClientSession() as session:

                    async with session.ws_connect(self.url) as ws:

                        async for msg in ws:

                            if msg.type == aiohttp.WSMsgType.TEXT:

                                t = msg.json()

                                trade = {
                                    "price": float(t["p"]),
                                    "qty": float(t["q"]),
                                    "buyer": not t["m"]
                                }

                                if self.callback:
                                    self.callback(trade)

            except Exception as e:

                print("Trades reconnect:", e)

                await asyncio.sleep(3)