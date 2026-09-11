
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QLabel

class PositionPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout=QVBoxLayout(self)
        self.side=QLabel("Side: None")
        self.entry=QLabel("Entry: --")
        self.stop=QLabel("SL: --")
        self.tp=QLabel("TP: --")
        self.pnl=QLabel("PnL: --")
        for w in (self.side,self.entry,self.stop,self.tp,self.pnl):
            layout.addWidget(w)

    def update_position(self,p):
        self.side.setText(f"Side: {p['side']}")
        self.entry.setText(f"Entry: {p['entry']}")
        self.stop.setText(f"SL: {p['stop']}")
        self.tp.setText(f"TP: {p['tp']}")
