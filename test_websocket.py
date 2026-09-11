import time
import json
from binance.ws.streams import ThreadedWebsocketManager

def handle_message(msg):
    if msg.get("e") == "error":
        print("Error:", msg)
        return

    print(json.dumps(msg, indent=2))

twm = ThreadedWebsocketManager()
twm.start()

conn_key = twm.start_kline_futures_socket(
    callback=handle_message,
    symbol="xauusdt",
    interval="3m"
)

print("Socket started:", conn_key)
print("Waiting for messages...")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    twm.stop()