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
from PyQt6.QtCore import QTimer, QRectF, QPointF
from PyQt6.QtGui import QColor, QPicture, QPainter

import pyqtgraph as pg
from pyqtgraph import InfiniteLine

from binance.client import Client

client = Client()

TIMEFRAMES = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "1H": "1h"
}


# ---------- Candlestick ----------

class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data):
        super().__init__()
        self.data = data
        self.picture = QPicture()
        self.generatePicture()

    def generatePicture(self):
        painter = QPainter(self.picture)

        width = 0.35

        for t, o, h, l, c in self.data:

            color = QColor(0, 255, 136) if c >= o else QColor(255, 77, 77)

            painter.setPen(pg.mkPen(color, width=1))
            painter.drawLine(QPointF(t, l), QPointF(t, h))

            painter.setBrush(pg.mkBrush(color))

            body_top = max(o, c)
            body_bottom = min(o, c)

            painter.drawRect(
                QRectF(
                    t - width,
                    body_bottom,
                    width * 2,
                    max(body_top - body_bottom, 0.02)
                )
            )

        painter.end()

    def paint(self, painter, option, widget):
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QRectF(self.picture.boundingRect())


# ---------- Main Window ----------

class Terminal(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("XAUUSDT Professional Trading Terminal")
        self.resize(1700, 950)

        self.current_tf = "3m"

        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)

        # Sidebar
        sidebar = QVBoxLayout()

        self.price_label = QLabel("Price: --")
        self.tf_label = QLabel("Timeframe: 3m")
        self.status_label = QLabel("Status: Connected")

        sidebar.addWidget(self.price_label)
        sidebar.addWidget(self.tf_label)
        sidebar.addWidget(self.status_label)
        sidebar.addStretch()

        # Chart Area
        chart_layout = QVBoxLayout()

        buttons = QHBoxLayout()

        for tf in TIMEFRAMES.keys():
            btn = QPushButton(tf)
            btn.clicked.connect(lambda _, x=tf: self.change_timeframe(x))
            buttons.addWidget(btn)

        chart_layout.addLayout(buttons)

        self.chart = pg.PlotWidget()

        self.chart.setBackground("#101010")

        self.chart.showGrid(x=True, y=True, alpha=0.25)

        self.chart.getAxis("left").setTextPen("white")
        self.chart.getAxis("bottom").setTextPen("white")

        chart_layout.addWidget(self.chart)

        layout.addLayout(sidebar, 1)
        layout.addLayout(chart_layout, 5)

        # Crosshair
        self.vLine = InfiniteLine(angle=90, movable=False)
        self.hLine = InfiniteLine(angle=0, movable=False)

        self.chart.addItem(self.vLine)
        self.chart.addItem(self.hLine)

        self.chart.scene().sigMouseMoved.connect(self.mouseMoved)

        # Refresh timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.load_chart)
        self.timer.start(3000)

        self.load_chart()

    # ----------------------------

    def mouseMoved(self, pos):

        vb = self.chart.plotItem.vb

        if self.chart.sceneBoundingRect().contains(pos):

            point = vb.mapSceneToView(pos)

            self.vLine.setPos(point.x())
            self.hLine.setPos(point.y())

    # ----------------------------

    def change_timeframe(self, tf):

        self.current_tf = tf
        self.tf_label.setText(f"Timeframe: {tf}")
        self.load_chart()

    # ----------------------------

    def load_chart(self):

        try:

            klines = client.futures_klines(
                symbol="XAUUSDT",
                interval=TIMEFRAMES[self.current_tf],
                limit=150
            )

            candles = []

            for i, k in enumerate(klines):

                candles.append((
                    i,
                    float(k[1]),  # open
                    float(k[2]),  # high
                    float(k[3]),  # low
                    float(k[4])   # close
                ))

            self.chart.clear()

            item = CandlestickItem(candles)

            self.chart.addItem(item)

            # Re-add crosshair after clear()
            self.chart.addItem(self.vLine)
            self.chart.addItem(self.hLine)

            highs = [c[2] for c in candles]
            lows = [c[3] for c in candles]
            closes = [c[4] for c in candles]

            self.chart.setXRange(0, len(candles))
            self.chart.setYRange(min(lows) - 1, max(highs) + 1)

            self.price_label.setText(f"Price: {closes[-1]:.2f}")

        except Exception as e:

            self.status_label.setText(f"Error: {e}")
            print("Chart Error:", e)


# ---------- Run ----------

if __name__ == "__main__":

    pg.setConfigOptions(antialias=True)

    app = QApplication(sys.argv)

    window = Terminal()

    window.show()

    sys.exit(app.exec())