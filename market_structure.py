class MarketStructure:
    def __init__(self, swing=3):
        self.swing = swing
        self.candles = []

    def update(self, candle):
        self.candles.append(candle)

        if len(self.candles) > 500:
            self.candles.pop(0)

    def swings(self):
        highs = []
        lows = []

        n = len(self.candles)

        for i in range(self.swing, n-self.swing):

            h = self.candles[i]["high"]
            l = self.candles[i]["low"]

            if h == max(c["high"] for c in self.candles[i-self.swing:i+self.swing+1]):
                highs.append((i, h))

            if l == min(c["low"] for c in self.candles[i-self.swing:i+self.swing+1]):
                lows.append((i, l))

        return highs, lows