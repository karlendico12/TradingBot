
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QLabel

class DOMPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout=QVBoxLayout(self)
        self.rows=[]
        for _ in range(20):
            lbl=QLabel("--")
            layout.addWidget(lbl)
            self.rows.append(lbl)

    def update_depth(self,bids,asks):
        rows=[]
        for p,q in reversed(asks[:10]):
            rows.append(f"ASK {p:.2f} {q:.3f}")
        for p,q in bids[:10]:
            rows.append(f"BID {p:.2f} {q:.3f}")
        for lbl,text in zip(self.rows,rows):
            lbl.setText(text)
