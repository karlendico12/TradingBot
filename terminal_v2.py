import sys

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel
)

from PyQt6.QtCore import QTimer, QRectF, QPointF, Qt
from PyQt6.QtGui import QColor, QPicture, QPainter

import pyqtgraph as pg

from binance.client import Client

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


# =====================================================
# Candlestick Graphics Object
# =====================================================

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


# =====================================================
# Trading Terminal
# =====================================================

class Terminal(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle("XAUUSDT Professional Trading Terminal")

        self.resize(1700,950)

        self.current_tf="3m"

        # -------- SMC --------

        self.ms=MarketStructure(swing=3)
        self.bos=BOSDetector()
        self.choch=CHoCHDetector()
        self.sweep=LiquiditySweepDetector()
        self.fvg=FVGDetector()
        self.ob=OrderBlockDetector()
        self.decision=TradeDecisionEngine()
        self.sr=SupportResistance()

        # -------- UI --------

        root=QWidget()

        self.setCentralWidget(root)

        layout=QHBoxLayout(root)

        # Sidebar

        side=QVBoxLayout()

        title=QLabel("XAUUSDT SMC Terminal")

        title.setStyleSheet("font-size:20px;font-weight:bold;color:white;")

        self.price=QLabel("Price: --")
        self.trend=QLabel("Trend: UNKNOWN")
        self.signal=QLabel("Trade Signal: Waiting")

        for w in [self.price,self.trend,self.signal]:
            w.setStyleSheet("font-size:14px;color:white;")

        side.addWidget(title)
        side.addSpacing(20)
        side.addWidget(self.price)
        side.addWidget(self.trend)
        side.addWidget(self.signal)
        side.addStretch()

        layout.addLayout(side,1)

        # Chart Area

        chart_layout=QVBoxLayout()

        row=QHBoxLayout()

        for tf in TIMEFRAMES.keys():

            b=QPushButton(tf)

            b.clicked.connect(lambda _,x=tf:self.change_timeframe(x))

            row.addWidget(b)

        chart_layout.addLayout(row)

        self.chart=pg.PlotWidget()

        self.chart.setBackground("#111111")

        self.chart.showGrid(x=True,y=True,alpha=.2)

        self.chart.getAxis("left").setTextPen("white")
        self.chart.getAxis("bottom").setTextPen("white")

        chart_layout.addWidget(self.chart)

        layout.addLayout(chart_layout,5)

        # Crosshair

        self.vLine=pg.InfiniteLine(angle=90,movable=False)
        self.hLine=pg.InfiniteLine(angle=0,movable=False)

        self.chart.addItem(self.vLine)
        self.chart.addItem(self.hLine)

        self.chart.scene().sigMouseMoved.connect(self.mouseMoved)

        # Auto refresh

        self.timer=QTimer()

        self.timer.timeout.connect(self.load_chart)

        self.timer.start(3000)

        self.load_chart()

    # =================================================

    def mouseMoved(self,pos):

        if self.chart.sceneBoundingRect().contains(pos):

            p=self.chart.plotItem.vb.mapSceneToView(pos)

            self.vLine.setPos(p.x())
            self.hLine.setPos(p.y())

    # =================================================

    def change_timeframe(self,tf):

        self.current_tf=tf

        self.load_chart()

    # =================================================

    def load_chart(self):

        try:

            klines=client.futures_klines(
                symbol="XAUUSDT",
                interval=TIMEFRAMES[self.current_tf],
                limit=120
            )

            self.ms.candles=[]

            candles=[]

            for i,k in enumerate(klines):

                candle={
                    "time":k[0],
                    "open":float(k[1]),
                    "high":float(k[2]),
                    "low":float(k[3]),
                    "close":float(k[4]),
                    "volume":float(k[5])
                }

                self.ms.update(candle)

                candles.append((
                    i,
                    candle["open"],
                    candle["high"],
                    candle["low"],
                    candle["close"]
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

            # -------------------------
            # Swing High
            # -------------------------

            for idx,price in highs[-8:]:

                self.chart.plot(
                    [idx],
                    [price],
                    pen=None,
                    symbol="t",
                    symbolBrush="yellow",
                    symbolSize=12
                )

            # -------------------------
            # Swing Low
            # -------------------------

            for idx,price in lows[-8:]:

                self.chart.plot(
                    [idx],
                    [price],
                    pen=None,
                    symbol="t1",
                    symbolBrush="cyan",
                    symbolSize=12
                )

            # -------------------------
            # Support Resistance
            # -------------------------

            for lv in levels:

                line=pg.InfiniteLine(
                    pos=lv,
                    angle=0,
                    pen=pg.mkPen(
                        "#666666",
                        style=Qt.PenStyle.DotLine
                    )
                )

                self.chart.addItem(line)

            # -------------------------
            # BOS
            # -------------------------

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

            # -------------------------
            # FVG
            # -------------------------

            for z in fvgs[-3:]:

                rect=pg.QtWidgets.QGraphicsRectItem(
                    QRectF(
                        0,
                        z["bottom"],
                        len(candles),
                        z["top"]-z["bottom"]
                    )
                )

                rect.setBrush(
                    pg.mkBrush(
                        (0,255,0,40)
                        if z["type"]=="bullish"
                        else
                        (255,0,0,40)
                    )
                )

                rect.setPen(pg.mkPen(None))

                self.chart.addItem(rect)

            # -------------------------
            # Order Blocks
            # -------------------------

            for b in obs[-3:]:

                rect=pg.QtWidgets.QGraphicsRectItem(
                    QRectF(
                        0,
                        b["bottom"],
                        len(candles),
                        b["top"]-b["bottom"]
                    )
                )

                rect.setBrush(
                    pg.mkBrush(
                        (0,255,0,20)
                        if b["type"]=="bullish"
                        else
                        (255,0,0,20)
                    )
                )

                rect.setPen(pg.mkPen(None))

                self.chart.addItem(rect)

            # -------------------------
            # Live Price
            # -------------------------

            price_line=pg.InfiniteLine(
                pos=latest["close"],
                angle=0,
                pen=pg.mkPen("white",width=1)
            )

            self.chart.addItem(price_line)

            label=pg.TextItem(
                text=f"{latest['close']:.2f}",
                color="white"
            )

            label.setPos(len(candles),latest["close"])

            self.chart.addItem(label)

            # -------------------------
            # Trade Arrow
            # -------------------------

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
                    f"{trade['side']}\n"
                    f"Score {trade['score']}/10\n"
                    f"Entry {trade['entry']:.2f}"
                )

            else:

                self.signal.setText("Trade Signal: Waiting")

            self.price.setText(
                f"Price: {latest['close']:.2f}"
            )

            self.trend.setText(
                f"Trend: {(self.choch.trend or 'UNKNOWN').upper()}"
            )

            highs_only=[c[2] for c in candles]
            lows_only=[c[3] for c in candles]

            self.chart.setXRange(0,len(candles))
            self.chart.setYRange(
                min(lows_only)-1,
                max(highs_only)+1
            )

        except Exception as e:

            print("Chart Error:",e)


# =====================================================
# Run
# =====================================================

if __name__=="__main__":

    pg.setConfigOptions(antialias=True)

    app=QApplication(sys.argv)

    window=Terminal()

    window.show()

    sys.exit(app.exec())