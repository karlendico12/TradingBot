
"""
terminal_v6.py
Final integrated terminal entry point.

Requirements:
    pip install pyqt6 pyqtgraph python-binance aiohttp qasync

Requires these project files in the same folder:
    websocket_feed.py
    market_structure.py
    bos_detector.py
    choch_detector.py
    liquidity_sweep.py
    fvg_detector.py
    order_block_detector.py
    trade_decision_engine.py
    support_resistance.py
    orderbook.py
    trades_tape.py
"""

import sys
import asyncio
from PyQt6.QtWidgets import (
    QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QLabel,QPushButton,QDoubleSpinBox,QSpinBox,QListWidget
)
from PyQt6.QtCore import QRectF,QPointF,Qt,QTimer
from PyQt6.QtGui import QColor,QPicture,QPainter
import pyqtgraph as pg
from pyqtgraph import DateAxisItem
from qasync import QEventLoop
from binance.client import Client

from websocket_feed import BinanceKlineFeed
from orderbook import OrderBookFeed
from trades_tape import TradesFeed

from market_structure import MarketStructure
from bos_detector import BOSDetector
from choch_detector import CHoCHDetector
from liquidity_sweep import LiquiditySweepDetector
from fvg_detector import FVGDetector
from order_block_detector import OrderBlockDetector
from trade_decision_engine import TradeDecisionEngine
from support_resistance import SupportResistance

client = Client()

TIMEFRAMES={"1m":"1m","3m":"3m","5m":"5m","15m":"15m","1H":"1h"}

class CandlestickItem(pg.GraphicsObject):
    def __init__(self,data):
        super().__init__()
        self.picture=QPicture()
        p=QPainter(self.picture)
        w=40
        for t,o,h,l,c in data:
            color=QColor(0,255,136) if c>=o else QColor(255,77,77)
            p.setPen(pg.mkPen(color,width=1))
            p.drawLine(QPointF(t,l),QPointF(t,h))
            p.setBrush(pg.mkBrush(color))
            p.drawRect(QRectF(t-w,min(o,c),w*2,max(abs(c-o),0.02)))
        p.end()
    def paint(self,p,*args): p.drawPicture(0,0,self.picture)
    def boundingRect(self): return QRectF(self.picture.boundingRect())

class Terminal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.symbol="XAUUSDT"
        self.tf="3m"

        self.ms=MarketStructure(swing=3)
        self.bos=BOSDetector()
        self.choch=CHoCHDetector()
        self.sweep=LiquiditySweepDetector()
        self.fvg=FVGDetector()
        self.ob=OrderBlockDetector()
        self.decision=TradeDecisionEngine()
        self.sr=SupportResistance()

        self.feed=BinanceKlineFeed(self.symbol,TIMEFRAMES[self.tf])
        self.feed.callback=self.on_tick

        self.book=OrderBookFeed(self.symbol)
        self.book.callback=self.update_book

        self.tape=TradesFeed(self.symbol)
        self.tape.callback=self.update_trade

        self.setWindowTitle("TradingBot v6 - Binance Futures XAUUSDT")
        self.resize(1850,1000)

        root=QWidget()
        self.setCentralWidget(root)
        layout=QHBoxLayout(root)

        side=QVBoxLayout()
        self.price=QLabel("Price --")
        self.trend=QLabel("Trend UNKNOWN")
        self.signal=QLabel("Signal Waiting")
        for w in (self.price,self.trend,self.signal):
            w.setStyleSheet("color:white;font-size:14px;")
        side.addWidget(QLabel("TradingBot v6"))
        side.addWidget(self.price)
        side.addWidget(self.trend)
        side.addWidget(self.signal)

        side.addWidget(QLabel("Depth of Market"))
        self.ask=QLabel("Ask --")
        self.bid=QLabel("Bid --")
        side.addWidget(self.ask)
        side.addWidget(self.bid)

        self.tape_list=QListWidget()
        self.tape_list.setMaximumHeight(220)
        side.addWidget(QLabel("Recent Trades"))
        side.addWidget(self.tape_list)

        side.addWidget(QLabel("Quantity"))
        self.qty=QDoubleSpinBox()
        self.qty.setDecimals(3)
        self.qty.setValue(0.01)
        side.addWidget(self.qty)

        side.addWidget(QLabel("Leverage"))
        self.lev=QSpinBox()
        self.lev.setRange(1,125)
        self.lev.setValue(20)
        side.addWidget(self.lev)

        self.buy=QPushButton("BUY (Safe)")
        self.sell=QPushButton("SELL (Safe)")
        self.buy.clicked.connect(self.buy_market)
        self.sell.clicked.connect(self.sell_market)
        side.addWidget(self.buy)
        side.addWidget(self.sell)
        side.addStretch()
        layout.addLayout(side,1)

        charts=QVBoxLayout()
        row=QHBoxLayout()
        for tf in TIMEFRAMES:
            b=QPushButton(tf)
            b.clicked.connect(lambda _,x=tf:self.change_tf(x))
            row.addWidget(b)
        charts.addLayout(row)

        self.chart=pg.PlotWidget(axisItems={"bottom":DateAxisItem()})
        self.chart.setBackground("#101010")
        self.chart.showGrid(x=True,y=True,alpha=.2)
        charts.addWidget(self.chart)

        self.volume=pg.PlotWidget(axisItems={"bottom":DateAxisItem()})
        self.volume.setMaximumHeight(170)
        self.volume.setBackground("#101010")
        self.volume.hideAxis("left")
        self.volume.setXLink(self.chart)
        charts.addWidget(self.volume)
        layout.addLayout(charts,5)

        self.vLine=pg.InfiniteLine(angle=90,movable=False)
        self.hLine=pg.InfiniteLine(angle=0,movable=False)
        self.chart.addItem(self.vLine)
        self.chart.addItem(self.hLine)
        self.chart.scene().sigMouseMoved.connect(self.mouse_moved)

        self.account_timer=QTimer()
        self.account_timer.timeout.connect(self.update_account)
        self.account_timer.start(5000)

        self.load_history()
        self.redraw()

    def change_tf(self,tf):
        self.tf=tf
        self.feed.interval=TIMEFRAMES[tf]
        self.load_history()
        self.redraw()

    def load_history(self):
        self.ms.candles=[]
        k=client.futures_klines(symbol=self.symbol,interval=TIMEFRAMES[self.tf],limit=150)
        for c in k:
            self.ms.update({
                "time":c[0],
                "open":float(c[1]),
                "high":float(c[2]),
                "low":float(c[3]),
                "close":float(c[4]),
                "volume":float(c[5])
            })

    def on_tick(self,c):
        if not self.ms.candles: return
        if self.ms.candles[-1]["time"]==c["time"]:
            self.ms.candles[-1]=c
        else:
            self.ms.candles.append(c)
            self.ms.candles=self.ms.candles[-150:]
            if c.get("closed"):
                self.auto_trade()
        self.redraw()

    def update_book(self,b):
        self.ask.setText(f"Ask {b['ask']:.2f} ({b['ask_qty']:.3f})")
        self.bid.setText(f"Bid {b['bid']:.2f} ({b['bid_qty']:.3f})")

    def update_trade(self,t):
        side="BUY" if t["buyer"] else "SELL"
        self.tape_list.insertItem(0,f"{t['price']:.2f} | {t['qty']:.3f} | {side}")
        while self.tape_list.count()>25:
            self.tape_list.takeItem(25)

    def mouse_moved(self,pos):
        if not self.chart.sceneBoundingRect().contains(pos): return
        p=self.chart.plotItem.vb.mapSceneToView(pos)
        self.vLine.setPos(p.x())
        self.hLine.setPos(p.y())

    def redraw(self):
        if not self.ms.candles: return
        data=[(c["time"]/1000,c["open"],c["high"],c["low"],c["close"]) for c in self.ms.candles]
        highs,lows=self.ms.swings()
        latest=self.ms.candles[-1]

        self.chart.clear()
        self.chart.addItem(CandlestickItem(data))
        self.chart.addItem(self.vLine)
        self.chart.addItem(self.hLine)

        for idx,p in highs[-8:]:
            self.chart.plot([self.ms.candles[idx]["time"]/1000],[p],pen=None,symbol="t",symbolBrush="yellow",symbolSize=12)
        for idx,p in lows[-8:]:
            self.chart.plot([self.ms.candles[idx]["time"]/1000],[p],pen=None,symbol="t1",symbolBrush="cyan",symbolSize=12)

        self.volume.clear()
        self.volume.addItem(pg.BarGraphItem(
            x=[c["time"]/1000 for c in self.ms.candles],
            height=[c["volume"] for c in self.ms.candles],
            width=120,
            brush="#4CAF50"
        ))

        self.price.setText(f"{self.symbol} {latest['close']:.2f}")

    def update_account(self):
        try:
            info=client.futures_account()
            self.trend.setText(f"Wallet {float(info['totalWalletBalance']):.2f} USDT")
        except Exception:
            pass

    def auto_trade(self):
        highs,lows=self.ms.swings()
        bos=self.bos.check(self.ms.candles,highs,lows)
        self.choch.update(bos)
        sweep=self.sweep.check(self.ms.candles,highs,lows)
        fvgs=self.fvg.update(self.ms.candles)
        obs=self.ob.update(self.ms.candles)
        sig=self.decision.evaluate(
            self.ms.candles[-1]["close"],
            self.choch.trend,bos,sweep,fvgs,obs
        )
        if sig:
            self.signal.setText(f"{sig['side']} Score {sig['score']}/10")
            print("SMC SIGNAL:",sig)

    def buy_market(self):
        print(f"SAFE BUY {self.qty.value()} {self.symbol}")

    def sell_market(self):
        print(f"SAFE SELL {self.qty.value()} {self.symbol}")

if __name__=="__main__":
    pg.setConfigOptions(antialias=True)
    app=QApplication(sys.argv)
    loop=QEventLoop(app)
    asyncio.set_event_loop(loop)
    win=Terminal()
    win.show()
    loop.create_task(win.feed.start())
    loop.create_task(win.book.start())
    loop.create_task(win.tape.start())
    with loop:
        loop.run_forever()
