import time
from binance.client import Client

from market_structure import MarketStructure
from bos_detector import BOSDetector
from choch_detector import CHoCHDetector
from liquidity_sweep import LiquiditySweepDetector
from fvg_detector import FVGDetector
from order_block_detector import OrderBlockDetector
from signal_engine import SignalEngine

client = Client()

ms = MarketStructure(swing=3)
bos = BOSDetector()
choch = CHoCHDetector()
sweep = LiquiditySweepDetector()
fvg = FVGDetector()
ob = OrderBlockDetector()
engine = SignalEngine()

loaded = False

print("Loading XAUUSDT 3-minute market structure...")

while True:
    try:
        # Load latest 100 candles
        klines = client.futures_klines(
            symbol="XAUUSDT",
            interval="3m",
            limit=100
        )

        # Refresh candle list
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

        latest = ms.candles[-1]

        highs, lows = ms.swings()

        bos_signal = bos.check(ms.candles, highs, lows)
        choch_signal = choch.update(bos_signal)
        sweep_signal = sweep.check(ms.candles, highs, lows)
        fvg_zones = fvg.update(ms.candles)
        order_blocks = ob.update(ms.candles)

        trade_signal = engine.generate(
            latest,
            bos_signal,
            choch.trend,
            sweep_signal,
            fvg_zones,
            order_blocks
        )

        if not loaded:
            print("Loaded 100 candles.")
            loaded = True

        print("\n" + "=" * 60)
        print(f"Current Close : {latest['close']:.2f}")

        if highs:
            print(f"Swing High   : {highs[-1][1]:.2f}")
        else:
            print("Swing High   : None")

        if lows:
            print(f"Swing Low    : {lows[-1][1]:.2f}")
        else:
            print("Swing Low    : None")

        # BOS
        if bos_signal:
            print("\n🚨 BREAK OF STRUCTURE")
            print(f"Direction    : {bos_signal['type'].upper()}")
            print(f"Break Level  : {bos_signal['level']:.2f}")
            print(f"Close Price  : {bos_signal['price']:.2f}")
        else:
            print("BOS Status   : Waiting")

        # CHoCH
        if choch_signal:
            print("\n🔄 CHANGE OF CHARACTER")
            print(f"{choch_signal['from'].upper()} → {choch_signal['to'].upper()}")
        else:
            trend = choch.trend.upper() if choch.trend else "UNKNOWN"
            print(f"Trend        : {trend}")

        # Liquidity Sweep
        if sweep_signal:
            print("\n💧 LIQUIDITY SWEEP")
            print(f"Side         : {sweep_signal['side']}")
            print(f"Sweep Level  : {sweep_signal['level']:.2f}")
            print(f"Close Price  : {sweep_signal['price']:.2f}")
        else:
            print("Sweep Status : Waiting")

        # Fair Value Gap
        if fvg_zones:
            latest_fvg = fvg_zones[-1]
            print("\n📦 FAIR VALUE GAP")
            print(f"Type         : {latest_fvg['type'].upper()}")
            print(f"Zone         : {latest_fvg['bottom']:.2f} → {latest_fvg['top']:.2f}")
        else:
            print("FVG Status   : None")

        # Order Block
        if order_blocks:
            latest_ob = order_blocks[-1]
            print("\n🏦 ORDER BLOCK")
            print(f"Type         : {latest_ob['type'].upper()}")
            print(f"Zone         : {latest_ob['bottom']:.2f} → {latest_ob['top']:.2f}")
        else:
            print("Order Block  : None")

        # Trade Signal
        if trade_signal:
            print("\n✅ TRADE SIGNAL")
            print(f"Side         : {trade_signal['side']}")
            print(f"Entry        : {trade_signal['entry']:.2f}")
            print(f"Stop Loss    : {trade_signal['sl']:.2f}")
            print(f"Take Profit1 : {trade_signal['tp1']:.2f}")
            print(f"Take Profit2 : {trade_signal['tp2']:.2f}")
            print(f"Risk/Reward  : {trade_signal['rr']}")
        else:
            print("Trade Signal : Waiting")

        time.sleep(3)

    except KeyboardInterrupt:
        print("\nStopped by user.")
        break

    except Exception as e:
        print("Error:", e)
        time.sleep(3)