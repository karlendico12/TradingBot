import asyncio
import websockets


async def main():

    url = "wss://fstream.binance.com/ws/xauusdt@kline_3m"

    print("Connecting...")
    
    async with websockets.connect(url) as ws:

        print("CONNECTED")

        while True:

            message = await ws.recv()

            print(message)


asyncio.run(main())