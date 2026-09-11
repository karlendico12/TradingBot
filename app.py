import asyncio
from websocket_manager import WS
from storage import save

def candle(c):

    if c["x"]:
        save(c)
        print(f'Saved candle: {c["c"]}')

ws = WS()
ws.subscribe(candle)

asyncio.run(ws.connect())