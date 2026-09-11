import sys
import asyncio
import aiohttp

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel
)

from PyQt6.QtCore import QRectF, QPointF, Qt
from PyQt6.QtGui import QColor, QPicture, QPainter

import pyqtgraph as pg
from qasync import QEventLoop

from binance.client import Client

# ---------- Existing SMC modules ----------
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
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "1H": "1h"
}


# ============================================================
# Binance Native WebSocket
# ============================================================

class BinanceKlineFeed:

    def __init__(self, symbol="xauusdt", interval="3m"):

        self.symbol = symbol.lower()
        self.interval = interval
        self.callback = None

    @property
    def url(self):
        return (
            f"wss://fstream.binance.com/ws/"
            f"{self.symbol}@kline_{self.interval}"
        )

    async def start(self):

        while True:

            try:

                async with aiohttp.ClientSession() as session:

                    async with session.ws_connect(self.url) as ws:

                        async for msg in ws:

                            if msg.type == aiohttp.WSMsgType.TEXT:

                                k = msg.json()["k"]

                                candle = {
                                    "time": k["t"],
                                    "open": float(k["o"]),
                                    "high": float(k["h"]),
                                    "low": float(k["l"]),
                                    "close": float(k["c"]),
                                    "volume": float(k["v"]),
                                    "closed": k["x"]
                                }

                                if self.callback:
                                    self.callback(candle)

            except Exception as e:

                print("Reconnect:", e)

                await asyncio.sleep(3)


# ============================================================
# Candlestick Item
# ============================================================

class CandlestickItem(pg.GraphicsObject):

    def __init__(self, data):

        super().__init__()

        self.picture = QPicture()

        self.generatePicture(data)

    def generatePicture(self, data):

        painter = QPainter(self.picture)

        width = 0.35

        for t, o, h, l, c in data:

            color = QColor(0,255,136) if c >= o else QColor(255,77,77)

            painter.setPen(pg.mkPen(color,width=1))
            painter.drawLine(QPointF(t,l), QPointF(t,h))

            painter.setBrush(pg.mkBrush(color))

            painter.drawRect(
                QRectF(
                    t-width,
                    min(o,c),
                    width*2,
                    max(abs(c-o),0.02)
                )
            )

        painter.end()

    def paint(self,painter,*args):
        painter.drawPicture(0,0,self.picture)

    def boundingRect(self):
        return QRectF(self.picture.boundingRect())


# ============================================================
# Terminal
# ============================================================

class Terminal(QMainWindow):

    def __init__(self):

        super().__init__()

        self.symbol = "XAUUSDT"
        self.current_tf = "3m"

        self.feed = BinanceKlineFeed(
            self.symbol,
            TIMEFRAMES[self.current_tf]
        )

        self.feed.callback = self.on_tick

        self.setWindowTitle("XAUUSDT Professional Trading Terminal")

        self.resize(1800,1000)

        # ---------- SMC ----------

        self.ms = MarketStructure(swing=3)
        self.bos = BOSDetector()
        self.choch = CHoCHDetector()
        self.sweep = LiquiditySweepDetector()
        self.fvg = FVGDetector()
        self.ob = OrderBlockDetector()
        self.decision = TradeDecisionEngine()
        self.sr = SupportResistance()

        # ---------- UI ----------

        root = QWidget()

        self.setCentralWidget(root)

        layout = QHBoxLayout(root)

        # Sidebar

        side = QVBoxLayout()

        title = QLabel("Professional Trading Terminal")

        title.setStyleSheet(
            "font-size:20px;font-weight:bold;color:white;"
        )

        self.price = QLabel("Price: --")
        self.trend = QLabel("Trend: UNKNOWN")
        self.signal = QLabel("Trade Signal: Waiting")

        for w in [self.price,self.trend,self.signal]:
            w.setStyleSheet("color:white;font-size:14px;")

        side.addWidget(title)
        side.addSpacing(15)
        side.addWidget(self.price)
        side.addWidget(self.trend)
        side.addWidget(self.signal)

        side.addSpacing(20)

        # Watchlist

        for s in ["XAUUSDT","BTCUSDT","ETHUSDT"]:

            b = QPushButton(s)

            b.clicked.connect(lambda _,x=s:self.change_symbol(x))

            side.addWidget(b)

        side.addStretch()

        layout.addLayout(side,1)

        # Chart Area

        chart_layout = QVBoxLayout()

        row = QHBoxLayout()

        for tf in TIMEFRAMES.keys():

            b = QPushButton(tf)

            b.clicked.connect(lambda _,x=tf:self.change_timeframe(x))

            row.addWidget(b)

        chart_layout.addLayout(row)

        self.chart = pg.PlotWidget()

        self.chart.setBackground("#101010")

        self.chart.showGrid(x=True,y=True,alpha=.2)

        self.chart.getAxis("left").setTextPen("white")
        self.chart.getAxis("bottom").setTextPen("white")

        chart_layout.addWidget(self.chart)

        # Volume chart

        self.volume_chart = pg.PlotWidget()

        self.volume_chart.setBackground("#101010")
        self.volume_chart.setMaximumHeight(160)

        chart_layout.addWidget(self.volume_chart)

        layout.addLayout(chart_layout,5)

        # Crosshair

        self.vLine = pg.InfiniteLine(angle=90,movable=False)
        self.hLine = pg.InfiniteLine(angle=0,movable=False)

        self.chart.addItem(self.vLine)
        self.chart.addItem(self.hLine)

        self.tooltip = pg.TextItem(color="white")

        self.chart.addItem(self.tooltip)

        self.chart.scene().sigMouseMoved.connect(self.mouseMoved)

        # Load initial history

        self.load_history()

        self.redraw_chart()

    # -------------------------------------------------------

    def load_history(self):

        klines = client.futures_klines(
            symbol=self.symbol,
            interval=TIMEFRAMES[self.current_tf],
            limit=150
        )

        self.ms.candles = []

        for k in klines:

            self.ms.update({
                "time":k[0],
                "open":float(k[1]),
                "high":float(k[2]),
                "low":float(k[3]),
                "close":float(k[4]),
                "volume":float(k[5])
            })

    # -------------------------------------------------------

    def on_tick(self,candle):

        if not self.ms.candles:
            return

        last = self.ms.candles[-1]

        if last["time"] == candle["time"]:

            self.ms.candles[-1] = candle

        else:

            self.ms.candles.append(candle)

            if len(self.ms.candles) > 150:
                self.ms.candles.pop(0)

        self.redraw_chart()

    # -------------------------------------------------------

    def change_timeframe(self,tf):

        self.current_tf = tf

        self.feed.interval = TIMEFRAMES[tf]

        self.load_history()

        self.redraw_chart()

    # -------------------------------------------------------

    def change_symbol(self,symbol):

        self.symbol = symbol

        self.feed.symbol = symbol.lower()

        self.load_history()

        self.redraw_chart()

    # -------------------------------------------------------

    def mouseMoved(self,pos):

        if not self.chart.sceneBoundingRect().contains(pos):
            return

        p = self.chart.plotItem.vb.mapSceneToView(pos)

        self.vLine.setPos(p.x())
        self.hLine.setPos(p.y())

        idx = int(round(p.x()))

        if 0 <= idx < len(self.ms.candles):

            c = self.ms.candles[idx]

            self.tooltip.setText(
                f"O {c['open']:.2f}\n"
                f"H {c['high']:.2f}\n"
                f"L {c['low']:.2f}\n"
                f"C {c['close']:.2f}"
            )

            self.tooltip.setPos(idx,c["high"])

    # -------------------------------------------------------

    def redraw_chart(self):

        candles=[]

        for i,c in enumerate(self.ms.candles):

            candles.append((
                i,
                c["open"],
                c["high"],
                c["low"],
                c["close"]
            ))

        highs,lows=self.ms.swings()

        levels=self.sr.levels(highs,lows)

        bos=self.bos.check(self.ms.candles,highs,lows)

        self.choch.update(bos)

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

        self.chart.addItem(CandlestickItem(candles))

        self.chart.addItem(self.vLine)
        self.chart.addItem(self.hLine)
        self.chart.addItem(self.tooltip)

        # Swing High

        for idx,p in highs[-8:]:

            self.chart.plot(
                [idx],[p],
                pen=None,
                symbol="t",
                symbolBrush="yellow",
                symbolSize=12
            )

        # Swing Low

        for idx,p in lows[-8:]:

            self.chart.plot(
                [idx],[p],
                pen=None,
                symbol="t1",
                symbolBrush="cyan",
                symbolSize=12
            )

        # Support Resistance

        for lv in levels:

            self.chart.addItem(

                pg.InfiniteLine(
                    pos=lv,
                    angle=0,
                    pen=pg.mkPen(
                        "#666666",
                        style=Qt.PenStyle.DotLine
                    )
                )
            )

        # BOS

        if bos:

            self.chart.addItem(

                pg.InfiniteLine(
                    pos=bos["level"],
                    angle=0,
                    pen=pg.mkPen(
                        "lime" if bos["type"]=="bullish" else "red",
                        width=2,
                        style=Qt.PenStyle.DashLine
                    )
                )
            )

        # Live price line

        self.chart.addItem(

            pg.InfiniteLine(
                pos=latest["close"],
                angle=0,
                pen=pg.mkPen("white",width=1)
            )
        )

        price_tag=pg.TextItem(
            text=f"{latest['close']:.2f}",
            anchor=(0,0.5),
            color="white"
        )

        price_tag.setPos(len(candles)-1,latest["close"])

        self.chart.addItem(price_tag)

        # Trade arrow

        if trade:

            self.chart.plot(
                [len(candles)-1],
                [trade["entry"]],
                pen=None,
                symbol="t"
                if trade["side"]=="BUY"
                else
                "t1",
                symbolBrush="lime"
                if trade["side"]=="BUY"
                else
                "red",
                symbolSize=20
            )

            self.signal.setText(
                f"{trade['side']} | "
                f"Score {trade['score']}/10"
            )

        else:

            self.signal.setText("Trade Signal: Waiting")

        # Volume

        self.volume_chart.clear()

        vols=[c["volume"] for c in self.ms.candles]

        self.volume_chart.addItem(

            pg.BarGraphItem(
                x=list(range(len(vols))),
                height=vols,
                width=0.8,
                brush="#4CAF50"
            )
        )

        # Sidebar

        self.price.setText(f"{self.symbol} {latest['close']:.2f}")

        self.trend.setText(
            f"Trend: {(self.choch.trend or 'UNKNOWN').upper()}"
        )

        highs_only=[c[2] for c in candles]
        lows_only=[c[3] for c in candles]

        self.chart.setXRange(0,len(candles))
        self.chart.setYRange(min(lows_only)-1,max(highs_only)+1)


# ============================================================
# Run
# ============================================================

pg.setConfigOptions(antialias=True)

app=QApplication(sys.argv)

loop=QEventLoop(app)

asyncio.set_event_loop(loop)

window=Terminal()

window.show()

loop.create_task(window.feed.start())

with loop:
    loop.run_forever()