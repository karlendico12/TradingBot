import time
from binance.client import Client

client = Client()

last_candle_time = None

print("Watching XAUUSDT 3-minute candles...")

while True:
    try:
        k = client.futures_klines(
            symbol="XAUUSDT",
            interval="3m",
            limit=1
        )[0]

        candle_time = k[0]

        if candle_time != last_candle_time:
            print("\n=== NEW 3-MINUTE CANDLE ===")
            last_candle_time = candle_time

        print(
            f"O:{k[1]}  "
            f"H:{k[2]}  "
            f"L:{k[3]}  "
            f"C:{k[4]}  "
            f"V:{k[5]}"
        )

        time.sleep(1)

    except Exception as e:
        print("Reconnect:", e)
        time.sleep(3)