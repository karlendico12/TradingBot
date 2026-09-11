
from PyQt6.QtCore import QRectF
import pyqtgraph as pg

class LiquidityHeatmap:
    def draw(self,chart,bids,asks,start_x,end_x):
        for p,q in bids[:10]:
            if q<5:
                continue
            r=pg.QtWidgets.QGraphicsRectItem(QRectF(start_x,p-0.1,end_x-start_x,0.2))
            r.setBrush(pg.mkBrush((0,255,0,30)))
            r.setPen(pg.mkPen(None))
            chart.addItem(r)

        for p,q in asks[:10]:
            if q<5:
                continue
            r=pg.QtWidgets.QGraphicsRectItem(QRectF(start_x,p-0.1,end_x-start_x,0.2))
            r.setBrush(pg.mkBrush((255,0,0,30)))
            r.setPen(pg.mkPen(None))
            chart.addItem(r)
