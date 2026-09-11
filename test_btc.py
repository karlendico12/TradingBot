import time
from binance.ws.streams import ThreadedWebsocketManager

def handle(msg):
    if msg.get("e") == "kline":
        print(msg["k"]["c"])

twm = ThreadedWebsocketManager()
twm.start()

twm.start_kline_futures_socket(
    callback=handle,
    symbol="btcusdt",
    interval="1m"
)

while True:
    time.sleep(1)