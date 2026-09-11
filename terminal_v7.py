
"""
TradingBot Version 7 (Integrated Main)
Run:
    python terminal_v7.py

This main file starts:
- Kline WebSocket
- Order Book WebSocket
- Trades WebSocket
- Existing SMC modules
"""

import sys
import asyncio
from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop
import pyqtgraph as pg

# Reuse the working v6 Terminal class
from terminal_v6 import Terminal

if __name__ == "__main__":
    pg.setConfigOptions(antialias=True)

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    win = Terminal()
    win.setWindowTitle("TradingBot V7")

    win.show()

    # These tasks were missing previously.
    loop.create_task(win.feed.start())
    loop.create_task(win.book.start())
    loop.create_task(win.tape.start())

    with loop:
        loop.run_forever()
