class TimeframeManager:
    def __init__(self):
        self.trends={"1h":None,"15m":None,"5m":None,"3m":None}

    def update(self,tf,trend):
        self.trends[tf]=trend

    def confirmed_buy(self):
        return all(self.trends[x]=="BULLISH" for x in ("1h","15m","5m"))

    def confirmed_sell(self):
        return all(self.trends[x]=="BEARISH" for x in ("1h","15m","5m"))
