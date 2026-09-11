
# terminal_v4.py
# Version 4 - Professional Trading Terminal
# Binance Futures + PyQt6 + PyQtGraph

import sys
import asyncio

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QPushButton, QHBoxLayout, QVBoxLayout,
    QDoubleSpinBox, QSpinBox
)
from PyQt6.QtCore import QRectF, QPointF, Qt
from PyQt6.QtGui import QColor, QPicture, QPainter

import pyqtgraph as pg
from pyqtgraph import DateAxisItem
from qasync import QEventLoop

from binance.client import Client

from websocket_feed import BinanceKlineFeed
from market_structure import MarketStructure
from bos_detector import BOSDetector
from choch_detector import CHoCHDetector
from liquidity_sweep import LiquiditySweepDetector
from fvg_detector import FVGDetector
from order_block_detector import OrderBlockDetector
from trade_decision_engine import TradeDecisionEngine
from support_resistance import SupportResistance

client = Client()

TIMEFRAMES = {
    "1m":"1m",
    "3m":"3m",
    "5m":"5m",
    "15m":"15m",
    "1H":"1h"
}

class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data):
        super().__init__()
        self.picture = QPicture()
        painter = QPainter(self.picture)
        width = 40
        for t,o,h,l,c in data:
            color = QColor(0,255,136) if c>=o else QColor(255,77,77)
            painter.setPen(pg.mkPen(color,width=1))
            painter.drawLine(QPointF(t,l),QPointF(t,h))
            painter.setBrush(pg.mkBrush(color))
            painter.drawRect(QRectF(t-width,min(o,c),width*2,max(abs(c-o),0.02)))
        painter.end()

    def paint(self,painter,*args):
        painter.drawPicture(0,0,self.picture)

    def boundingRect(self):
        return QRectF(self.picture.boundingRect())

class Terminal(QMainWindow):
    def __init__(self):
        super().__init__()

        self.symbol="XAUUSDT"
        self.tf="3m"

        self.feed=BinanceKlineFeed(self.symbol,TIMEFRAMES[self.tf])
        self.feed.callback=self.on_tick

        self.ms=MarketStructure(swing=3)
        self.bos=BOSDetector()
        self.choch=CHoCHDetector()
        self.sweep=LiquiditySweepDetector()
        self.fvg=FVGDetector()
        self.ob=OrderBlockDetector()
        self.decision=TradeDecisionEngine()
        self.sr=SupportResistance()

        self.setWindowTitle("Professional Trading Terminal")
        self.resize(1800,1000)

        root=QWidget()
        self.setCentralWidget(root)
        layout=QHBoxLayout(root)

        self.build_sidebar(layout)
        self.build_chart(layout)

        self.load_history()
        self.redraw()

    def build_sidebar(self,layout):
        side=QVBoxLayout()

        title=QLabel("Professional Trading Terminal")
        title.setStyleSheet("font-size:22px;font-weight:bold;color:white;")

        self.price=QLabel("Price --")
        self.trend=QLabel("Trend UNKNOWN")
        self.signal=QLabel("Trade Signal Waiting")

        for w in (self.price,self.trend,self.signal):
            w.setStyleSheet("color:white;font-size:14px;")

        side.addWidget(title)
        side.addWidget(self.price)
        side.addWidget(self.trend)
        side.addWidget(self.signal)

        side.addSpacing(15)

        for s in ("XAUUSDT","BTCUSDT","ETHUSDT"):
            b=QPushButton(s)
            b.clicked.connect(lambda _,x=s:self.change_symbol(x))
            side.addWidget(b)

        side.addSpacing(15)

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

        buy=QPushButton("BUY")
        sell=QPushButton("SELL")

        buy.setStyleSheet("background:#00aa66;color:white;")
        sell.setStyleSheet("background:#aa3333;color:white;")

        side.addWidget(buy)
        side.addWidget(sell)
        side.addStretch()

        layout.addLayout(side,1)

    def build_chart(self,layout):
        chart_layout=QVBoxLayout()

        buttons=QHBoxLayout()

        for tf in TIMEFRAMES:
            b=QPushButton(tf)
            b.clicked.connect(lambda _,x=tf:self.change_tf(x))
            buttons.addWidget(b)

        chart_layout.addLayout(buttons)

        price_axis=DateAxisItem()
        volume_axis=DateAxisItem()

        self.chart=pg.PlotWidget(axisItems={"bottom":price_axis})
        self.chart.setBackground("#101010")
        self.chart.showGrid(x=True,y=True,alpha=.2)
        self.chart.setMouseEnabled(True,True)
        chart_layout.addWidget(self.chart)

        self.volume=pg.PlotWidget(axisItems={"bottom":volume_axis})
        self.volume.setBackground("#101010")
        self.volume.setMaximumHeight(170)
        self.volume.hideAxis("left")
        self.volume.showGrid(x=True,y=True,alpha=.2)
        self.volume.setXLink(self.chart)
        chart_layout.addWidget(self.volume)

        layout.addLayout(chart_layout,5)

        self.vLine=pg.InfiniteLine(angle=90,movable=False)
        self.hLine=pg.InfiniteLine(angle=0,movable=False)
        self.tooltip=pg.TextItem(color="white")

        self.chart.addItem(self.vLine)
        self.chart.addItem(self.hLine)
        self.chart.addItem(self.tooltip)
        self.chart.scene().sigMouseMoved.connect(self.mouseMoved)

    def change_tf(self,tf):
        self.tf=tf
        self.feed.interval=TIMEFRAMES[tf]
        self.load_history()
        self.redraw()

    def change_symbol(self,symbol):
        self.symbol=symbol
        self.feed.symbol=symbol.lower()
        self.load_history()
        self.redraw()

    def load_history(self):
        self.ms.candles=[]
        klines=client.futures_klines(symbol=self.symbol,interval=TIMEFRAMES[self.tf],limit=150)

        for k in klines:
            self.ms.update({
                "time":k[0],
                "open":float(k[1]),
                "high":float(k[2]),
                "low":float(k[3]),
                "close":float(k[4]),
                "volume":float(k[5])
            })

    def on_tick(self,candle):
        if not self.ms.candles:
            return

        if self.ms.candles[-1]["time"]==candle["time"]:
            self.ms.candles[-1]=candle
        else:
            self.ms.candles.append(candle)
            self.ms.candles=self.ms.candles[-150:]

        self.redraw()

    def mouseMoved(self,pos):
        if not self.chart.sceneBoundingRect().contains(pos):
            return

        p=self.chart.plotItem.vb.mapSceneToView(pos)

        self.vLine.setPos(p.x())
        self.hLine.setPos(p.y())

        nearest=min(self.ms.candles,key=lambda x:abs(x["time"]/1000-p.x()))

        self.tooltip.setText(
            f"O {nearest['open']:.2f}\n"
            f"H {nearest['high']:.2f}\n"
            f"L {nearest['low']:.2f}\n"
            f"C {nearest['close']:.2f}"
        )

        self.tooltip.setPos(nearest["time"]/1000,nearest["high"])

    def redraw(self):
        data=[
            (c["time"]/1000,c["open"],c["high"],c["low"],c["close"])
            for c in self.ms.candles
        ]

        highs,lows=self.ms.swings()
        levels=self.sr.levels(highs,lows)

        bos=self.bos.check(self.ms.candles,highs,lows)
        choch=self.choch.update(bos)

        sweep=self.sweep.check(self.ms.candles,highs,lows)
        fvgs=self.fvg.update(self.ms.candles)
        obs=self.ob.update(self.ms.candles)

        latest=self.ms.candles[-1]

        trade=self.decision.evaluate(
            latest["close"],
            self.choch.trend,
            bos,
            sweep,
            fvgs,
            obs
        )

        self.chart.clear()

        self.chart.addItem(CandlestickItem(data))
        self.chart.addItem(self.vLine)
        self.chart.addItem(self.hLine)
        self.chart.addItem(self.tooltip)

        for idx,price in highs[-8:]:
            self.chart.plot(
                [self.ms.candles[idx]["time"]/1000],
                [price],
                pen=None,
                symbol="t",
                symbolBrush="yellow",
                symbolSize=12
            )

        for idx,price in lows[-8:]:
            self.chart.plot(
                [self.ms.candles[idx]["time"]/1000],
                [price],
                pen=None,
                symbol="t1",
                symbolBrush="cyan",
                symbolSize=12
            )

        for level in levels:
            self.chart.addItem(
                pg.InfiniteLine(
                    pos=level,
                    angle=0,
                    pen=pg.mkPen("#666",style=Qt.PenStyle.DotLine)
                )
            )

        if bos:
            color="lime" if bos["type"]=="bullish" else "red"

            self.chart.addItem(
                pg.InfiniteLine(
                    pos=bos["level"],
                    angle=0,
                    pen=pg.mkPen(color,width=2,style=Qt.PenStyle.DashLine)
                )
            )

            label=pg.TextItem(
                text=f"BOS {bos['type'].upper()}",
                color=color
            )

            label.setPos(data[-1][0],bos["level"])
            self.chart.addItem(label)

        if choch:
            label=pg.TextItem(text="CHoCH",color="orange")
            label.setPos(data[-1][0],latest["close"])
            self.chart.addItem(label)

        for zone in fvgs[-3:]:
            if "index" not in zone:
                continue

            start=self.ms.candles[zone["index"]]["time"]/1000

            rect=pg.QtWidgets.QGraphicsRectItem(
                QRectF(start,zone["bottom"],data[-1][0]-start,zone["top"]-zone["bottom"])
            )

            rect.setBrush(pg.mkBrush((0,255,0,40) if zone["type"]=="bullish" else (255,0,0,40)))
            rect.setPen(pg.mkPen(None))
            self.chart.addItem(rect)

        for block in obs[-3:]:
            if "index" not in block:
                continue

            start=self.ms.candles[block["index"]]["time"]/1000

            rect=pg.QtWidgets.QGraphicsRectItem(
                QRectF(start,block["bottom"],data[-1][0]-start,block["top"]-block["bottom"])
            )

            rect.setBrush(pg.mkBrush((0,255,0,20) if block["type"]=="bullish" else (255,0,0,20)))
            rect.setPen(pg.mkPen(None))
            self.chart.addItem(rect)

        self.chart.addItem(
            pg.InfiniteLine(pos=latest["close"],angle=0,pen=pg.mkPen("white"))
        )

        tag=pg.TextItem(text=f"{latest['close']:.2f}",anchor=(0,0.5),color="white")
        tag.setPos(data[-1][0],latest["close"])
        self.chart.addItem(tag)

        if trade:
            self.chart.plot(
                [data[-1][0]],
                [trade["entry"]],
                pen=None,
                symbol="t" if trade["side"]=="BUY" else "t1",
                symbolBrush="lime" if trade["side"]=="BUY" else "red",
                symbolSize=18
            )
            self.signal.setText(f"{trade['side']}  Score {trade['score']}/10")
        else:
            self.signal.setText("Trade Signal Waiting")

        self.price.setText(f"{self.symbol} {latest['close']:.2f}")
        self.trend.setText(f"Trend {(self.choch.trend or 'UNKNOWN').upper()}")

        self.volume.clear()

        self.volume.addItem(
            pg.BarGraphItem(
                x=[c["time"]/1000 for c in self.ms.candles],
                height=[c["volume"] for c in self.ms.candles],
                width=120,
                brush="#4CAF50"
            )
        )

if __name__=="__main__":
    pg.setConfigOptions(antialias=True)

    app=QApplication(sys.argv)

    loop=QEventLoop(app)
    asyncio.set_event_loop(loop)

    window=Terminal()
    window.show()

    loop.create_task(window.feed.start())

    with loop:
        loop.run_forever()
