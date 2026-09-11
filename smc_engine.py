
class MultiTimeframeSMC:
    def __init__(self):
        self.status = {
            "1h": "UNKNOWN",
            "15m": "UNKNOWN",
            "5m": "UNKNOWN",
            "3m": "UNKNOWN"
        }

    def update(self, timeframe, trend):
        self.status[timeframe] = trend

    def confirmed_buy(self):
        return (
            self.status["1h"] == "BULLISH" and
            self.status["15m"] == "BULLISH" and
            self.status["5m"] == "BULLISH"
        )

    def confirmed_sell(self):
        return (
            self.status["1h"] == "BEARISH" and
            self.status["15m"] == "BEARISH" and
            self.status["5m"] == "BEARISH"
        )
