from datetime import datetime

class CandleBuilder:
    def __init__(self):
        self.current = None

    def update(self, price):
        now = datetime.utcnow()

        # Round down to the nearest 3-minute interval
        minute = (now.minute // 3) * 3

        candle_time = now.replace(
            minute=minute,
            second=0,
            microsecond=0
        )

        # First candle
        if self.current is None:
            self.current = {
                "time": candle_time,
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }
            return None

        # New candle started
        if candle_time != self.current["time"]:
            finished = self.current

            self.current = {
                "time": candle_time,
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }

            return finished

        # Update current candle
        self.current["high"] = max(self.current["high"], price)
        self.current["low"] = min(self.current["low"], price)
        self.current["close"] = price

        return None