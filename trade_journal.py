
import json
from pathlib import Path
from datetime import datetime

class TradeJournal:
    def __init__(self,path="Trades"):
        self.path=Path(path)
        self.path.mkdir(exist_ok=True)

    def save(self,trade):
        ts=datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(self.path/f"{ts}.json","w") as f:
            json.dump(trade,f,indent=2)
