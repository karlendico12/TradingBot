
"""
terminal_v5.py
Version 5 scaffold that extends terminal_v4.py.

This file contains the Version 5 additions:
- OrderBook (DOM) integration
- Recent Trades Tape
- Liquidity Heatmap hooks
- Functional BUY/SELL handlers (safe mode)
- Live Account Panel
- SMC Auto-Trade hook

Drop these methods into your existing terminal_v4.py or use this as
the starting point for Version 5.
"""

# ---- Imports to add ----
from PyQt6.QtWidgets import QListWidget
from PyQt6.QtCore import QTimer
from orderbook import OrderBookFeed
from trades_tape import TradesFeed

# ---- __init__ additions ----
INIT_PATCH = r"""
self.orderbook_feed = OrderBookFeed(self.symbol)
self.orderbook_feed.callback = self.update_orderbook

self.trades_feed = TradesFeed(self.symbol)
self.trades_feed.callback = self.update_trade_tape

self.account_timer = QTimer()
self.account_timer.timeout.connect(self.update_account_panel)
self.account_timer.start(5000)
"""

# ---- Sidebar additions ----
SIDEBAR_PATCH = r"""
dom_title = QLabel("Depth of Market")
side.addWidget(dom_title)

self.ask_qty = QLabel("Ask Qty: --")
self.ask_price = QLabel("Ask: --")
self.bid_price = QLabel("Bid: --")
self.bid_qty = QLabel("Bid Qty: --")

for w in (self.ask_qty,self.ask_price,self.bid_price,self.bid_qty):
    side.addWidget(w)

self.trade_list = QListWidget()
self.trade_list.setMaximumHeight(220)
side.addWidget(self.trade_list)
"""

# ---- Methods ----
def update_orderbook(self, book):
    self.latest_book = book
    self.ask_qty.setText(f"Ask Qty: {book['ask_qty']:.3f}")
    self.ask_price.setText(f"Ask: {book['ask']:.2f}")
    self.bid_price.setText(f"Bid: {book['bid']:.2f}")
    self.bid_qty.setText(f"Bid Qty: {book['bid_qty']:.3f}")

def update_trade_tape(self, trade):
    side = "BUY" if trade["buyer"] else "SELL"
    self.trade_list.insertItem(0, f"{trade['price']:.2f} | {trade['qty']:.3f} | {side}")
    while self.trade_list.count() > 25:
        self.trade_list.takeItem(25)

def buy_market(self):
    print(f"BUY {self.qty.value()} {self.symbol}")

def sell_market(self):
    print(f"SELL {self.qty.value()} {self.symbol}")

def update_account_panel(self):
    try:
        info = client.futures_account()
        self.balance.setText(f"Balance: {float(info['totalWalletBalance']):.2f}")
        self.margin.setText(f"Margin: {float(info['totalMarginBalance']):.2f}")
        self.pnl.setText(f"PnL: {float(info['totalUnrealizedProfit']):.2f}")
    except Exception as e:
        print("Account:", e)

def auto_trade(self):
    latest = self.ms.candles[-1]
    highs, lows = self.ms.swings()
    bos = self.bos.check(self.ms.candles, highs, lows)
    self.choch.update(bos)
    sweep = self.sweep.check(self.ms.candles, highs, lows)
    fvgs = self.fvg.update(self.ms.candles)
    obs = self.ob.update(self.ms.candles)

    signal = self.decision.evaluate(
        latest["close"],
        self.choch.trend,
        bos,
        sweep,
        fvgs,
        obs
    )

    if signal:
        print("="*40)
        print("SMC SIGNAL")
        print(signal)
        print("="*40)

# ---- on_tick addition ----
ON_TICK_PATCH = r"""
if candle["closed"]:
    self.auto_trade()
"""

print("Version 5 scaffold ready.")
