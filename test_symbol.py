from binance.client import Client

client = Client()

info = client.futures_exchange_info()

found = False

for s in info["symbols"]:
    if s["symbol"] == "XAUUSDT":
        found = True
        print("FOUND")
        print(s)
        break

if not found:
    print("XAUUSDT NOT FOUND")