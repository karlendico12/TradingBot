class CHoCHDetector:
    def __init__(self):
        self.trend = None

    def update(self, bos_signal):
        if bos_signal is None:
            return None

        new_trend = "bullish" if bos_signal["type"] == "bullish" else "bearish"

        if self.trend is None:
            self.trend = new_trend
            return None

        if new_trend != self.trend:
            old = self.trend
            self.trend = new_trend
            return {
                "from": old,
                "to": new_trend
            }

        return None