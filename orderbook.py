import asyncio
import aiohttp

class OrderBookFeed:

    def __init__(self, symbol="xauusdt"):
        self.symbol = symbol.lower()
        self.callback = None

    @property
    def url(self):
        return f"wss://fstream.binance.com/ws/{self.symbol}@bookTicker"

    async def start(self):

        while True:

            try:

                async with aiohttp.ClientSession() as session:

                    async with session.ws_connect(self.url) as ws:

                        async for msg in ws:

                            if msg.type == aiohttp.WSMsgType.TEXT:

                                data = msg.json()

                                book = {
                                    "bid": float(data["b"]),
                                    "bid_qty": float(data["B"]),
                                    "ask": float(data["a"]),
                                    "ask_qty": float(data["A"])
                                }

                                if self.callback:
                                    self.callback(book)

            except Exception as e:

                print("OrderBook reconnect:", e)

                await asyncio.sleep(3)