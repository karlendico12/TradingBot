import asyncio
import json
import websockets

URL = "wss://fstream.binance.com/public/ws/xauusdt@kline_3m"

class WS:
    def __init__(self):
        self.callbacks = []

    def subscribe(self, callback):
        self.callbacks.append(callback)

    async def connect(self):
        while True:
            try:
                print("Connecting...")

                async with websockets.connect(URL, ping_interval=20) as ws:

                    print("Connected!")

                    async for raw in ws:

                        msg = json.loads(raw)

                        if "k" in msg:

                            candle = msg["k"]

                            print(
                                f'Live {candle["c"]} | Closed={candle["x"]}'
                            )

                            for cb in self.callbacks:
                                cb(candle)

            except Exception as e:

                print("Reconnect:", e)

                await asyncio.sleep(5)