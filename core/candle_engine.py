class CandleEngine:

    def __init__(self):
        self.candles = []

    # Existing method (kept for compatibility)
    def update(self, candle):

        if not self.candles:
            self.candles.append(candle)
            return

        if self.candles[-1]["time"] == candle["time"]:
            self.candles[-1] = candle
        else:
            self.candles.append(candle)
            self.candles = self.candles[-500:]

    # V8 compatibility
    def add_candle(self, candle):
        self.update(candle)

    # V8 compatibility
    def get_candles(self):
        return self.candles