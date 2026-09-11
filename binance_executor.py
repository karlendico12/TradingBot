
from binance.client import Client

class BinanceExecutor:
    def __init__(self, api_key, api_secret, testnet=True):
        self.client = Client(api_key, api_secret)
        if testnet:
            self.client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"

    def market_buy(self, symbol, qty):
        return self.client.futures_create_order(
            symbol=symbol,
            side="BUY",
            type="MARKET",
            quantity=qty
        )

    def market_sell(self, symbol, qty):
        return self.client.futures_create_order(
            symbol=symbol,
            side="SELL",
            type="MARKET",
            quantity=qty
        )

    def stop_market(self, symbol, side, stop_price, qty):
        return self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type="STOP_MARKET",
            stopPrice=stop_price,
            quantity=qty
        )

    def take_profit_market(self, symbol, side, tp_price, qty):
        return self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp_price,
            quantity=qty
        )
