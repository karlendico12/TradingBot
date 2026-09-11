import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import matplotlib.dates as mdates
import pandas as pd

from binance.client import Client

from market_structure import MarketStructure
from bos_detector import BOSDetector
from choch_detector import CHoCHDetector
from liquidity_sweep import LiquiditySweepDetector
from fvg_detector import FVGDetector
from order_block_detector import OrderBlockDetector
from trade_decision_engine import TradeDecisionEngine
from support_resistance import SupportResistance

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

client = Client()

ms = MarketStructure(swing=3)
bos = BOSDetector()
choch = CHoCHDetector()
sweep = LiquiditySweepDetector()
fvg = FVGDetector()
ob = OrderBlockDetector()
decision = TradeDecisionEngine()
sr = SupportResistance()


class Dashboard:
    def __init__(self):

        self.root = ctk.CTk()
        self.root.title("XAUUSDT Professional Trading Terminal")
        self.root.geometry("1600x920")

        left = ctk.CTkFrame(self.root, width=320)
        left.pack(side="left", fill="y", padx=10, pady=10)

        right = ctk.CTkFrame(self.root)
        right.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            left,
            text="XAUUSDT SMC Terminal",
            font=("Arial", 24, "bold")
        ).pack(pady=15)

        self.price = ctk.CTkLabel(left, text="Price: --")
        self.price.pack(anchor="w", padx=12)

        self.swing_high = ctk.CTkLabel(left, text="Swing High: --")
        self.swing_high.pack(anchor="w", padx=12)

        self.swing_low = ctk.CTkLabel(left, text="Swing Low: --")
        self.swing_low.pack(anchor="w", padx=12)

        self.bos_label = ctk.CTkLabel(left, text="BOS: Waiting")
        self.bos_label.pack(anchor="w", padx=12)

        self.trend = ctk.CTkLabel(left, text="Trend: UNKNOWN")
        self.trend.pack(anchor="w", padx=12)

        self.signal = ctk.CTkLabel(
            left,
            text="Trade Signal\nWaiting",
            font=("Arial", 16, "bold"),
            justify="left"
        )
        self.signal.pack(anchor="w", padx=12, pady=20)

        self.fig = Figure(figsize=(12, 7), dpi=100)
        self.fig.patch.set_facecolor("#121212")

        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("#121212")

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.update_chart()

        self.root.mainloop()

    def draw_candles(self, df):

        width = 0.0012

        for _, row in df.iterrows():

            color = "#00ff88" if row["close"] >= row["open"] else "#ff4d4d"

            self.ax.plot(
                [row["time"], row["time"]],
                [row["low"], row["high"]],
                color=color,
                linewidth=1
            )

            bottom = min(row["open"], row["close"])
            height = max(abs(row["close"] - row["open"]), 0.02)

            self.ax.add_patch(
                Rectangle(
                    (mdates.date2num(row["time"]) - width / 2, bottom),
                    width,
                    height,
                    color=color
                )
            )

    def update_chart(self):

        try:
            klines = client.futures_klines(
                symbol="XAUUSDT",
                interval="3m",
                limit=120
            )

            ms.candles = []

            for k in klines:
                ms.update({
                    "time": k[0],
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5])
                })

            highs, lows = ms.swings()
            levels = sr.levels(highs, lows)

            bos_signal = bos.check(ms.candles, highs, lows)
            choch.update(bos_signal)
            sweep_signal = sweep.check(ms.candles, highs, lows)
            fvg_zones = fvg.update(ms.candles)
            order_blocks = ob.update(ms.candles)

            latest = ms.candles[-1]

            trade = decision.evaluate(
                latest["close"],
                choch.trend,
                bos_signal,
                sweep_signal,
                fvg_zones,
                order_blocks
            )

            df = pd.DataFrame(ms.candles)
            df["time"] = pd.to_datetime(df["time"], unit="ms")

            self.ax.clear()
            self.ax.set_facecolor("#121212")

            self.draw_candles(df)

            # Swing Highs
            for idx, price in highs[-8:]:
                self.ax.scatter(
                    df.iloc[idx]["time"],
                    price,
                    color="yellow",
                    marker="^",
                    s=60,
                    zorder=5
                )

            # Swing Lows
            for idx, price in lows[-8:]:
                self.ax.scatter(
                    df.iloc[idx]["time"],
                    price,
                    color="cyan",
                    marker="v",
                    s=60,
                    zorder=5
                )

            # Support & Resistance
            for level in levels:
                self.ax.axhline(
                    level,
                    color="#777777",
                    linestyle=":",
                    linewidth=0.8,
                    alpha=0.7
                )

                self.ax.text(
                    df["time"].iloc[-1],
                    level,
                    f"{level:.2f}",
                    color="#BBBBBB",
                    fontsize=8,
                    va="center"
                )

            # BOS Line
            if bos_signal:
                color = "lime" if bos_signal["type"] == "bullish" else "red"

                self.ax.axhline(
                    bos_signal["level"],
                    color=color,
                    linestyle="--",
                    linewidth=1.3
                )

            # Fair Value Gaps
            for zone in fvg_zones[-3:]:
                color = "#00AA00" if zone["type"] == "bullish" else "#AA0000"

                self.ax.axhspan(
                    zone["bottom"],
                    zone["top"],
                    color=color,
                    alpha=0.18
                )

            # Order Blocks
            for block in order_blocks[-3:]:
                color = "#00FF88" if block["type"] == "bullish" else "#FF5555"

                self.ax.axhspan(
                    block["bottom"],
                    block["top"],
                    color=color,
                    alpha=0.08
                )

            # Live Price Line
            self.ax.axhline(
                latest["close"],
                color="white",
                linewidth=0.9
            )

            # BUY / SELL Arrow
            if trade:
                self.ax.scatter(
                    df["time"].iloc[-1],
                    trade["entry"],
                    color="lime" if trade["side"] == "BUY" else "red",
                    marker="^" if trade["side"] == "BUY" else "v",
                    s=180,
                    zorder=10
                )

            self.ax.set_title(
                "XAUUSDT • 3 Minute • Smart Money Concepts",
                color="white",
                fontsize=14
            )

            self.ax.tick_params(colors="white")
            self.ax.grid(alpha=0.12)

            self.fig.autofmt_xdate()

            # Sidebar
            self.price.configure(text=f"Price: {latest['close']:.2f}")

            self.swing_high.configure(
                text=f"Swing High: {highs[-1][1]:.2f}" if highs else "Swing High: --"
            )

            self.swing_low.configure(
                text=f"Swing Low: {lows[-1][1]:.2f}" if lows else "Swing Low: --"
            )

            if bos_signal:
                self.bos_label.configure(
                    text=f"BOS: {bos_signal['type'].upper()} @ {bos_signal['level']:.2f}"
                )
            else:
                self.bos_label.configure(text="BOS: Waiting")

            self.trend.configure(
                text=f"Trend: {(choch.trend or 'UNKNOWN').upper()}"
            )

            if trade:
                self.signal.configure(
                    text=(
                        f"✅ {trade['side']}\n\n"
                        f"Score: {trade['score']}/10\n"
                        f"Entry: {trade['entry']:.2f}\n"
                        f"SL: {trade['sl']:.2f}\n"
                        f"TP1: {trade['tp1']:.2f}\n"
                        f"TP2: {trade['tp2']:.2f}"
                    ),
                    text_color="#00FF88"
                )
            else:
                self.signal.configure(
                    text="Trade Signal\nWaiting",
                    text_color="white"
                )

            self.canvas.draw()

        except Exception as e:
            print("Dashboard Error:", e)

        self.root.after(3000, self.update_chart)


if __name__ == "__main__":
    Dashboard()