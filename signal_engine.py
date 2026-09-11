class SignalEngine:
    def __init__(self):
        self.last_signal = None

    def generate(
        self,
        candle,
        bos_signal,
        choch_trend,
        sweep_signal,
        fvg_zones,
        order_blocks
    ):
        price = candle["close"]

        # ---------------- BUY ----------------

        if (
            bos_signal
            and bos_signal["type"] == "bullish"
            and choch_trend == "bullish"
        ):

            bullish_fvg = next(
                (
                    z for z in reversed(fvg_zones)
                    if z["type"] == "bullish"
                    and z["bottom"] <= price <= z["top"]
                ),
                None
            )

            bullish_ob = next(
                (
                    z for z in reversed(order_blocks)
                    if z["type"] == "bullish"
                    and z["bottom"] <= price <= z["top"]
                ),
                None
            )

            if bullish_fvg and bullish_ob:

                signal = ("BUY", price)

                if signal != self.last_signal:
                    self.last_signal = signal

                    sl = bullish_ob["bottom"]
                    risk = price - sl
                    tp1 = price + risk * 2
                    tp2 = price + risk * 3

                    return {
                        "side": "BUY",
                        "entry": price,
                        "sl": sl,
                        "tp1": tp1,
                        "tp2": tp2,
                        "rr": "1:3"
                    }

        # ---------------- SELL ----------------

        if (
            bos_signal
            and bos_signal["type"] == "bearish"
            and choch_trend == "bearish"
        ):

            bearish_fvg = next(
                (
                    z for z in reversed(fvg_zones)
                    if z["type"] == "bearish"
                    and z["bottom"] <= price <= z["top"]
                ),
                None
            )

            bearish_ob = next(
                (
                    z for z in reversed(order_blocks)
                    if z["type"] == "bearish"
                    and z["bottom"] <= price <= z["top"]
                ),
                None
            )

            if bearish_fvg and bearish_ob:

                signal = ("SELL", price)

                if signal != self.last_signal:
                    self.last_signal = signal

                    sl = bearish_ob["top"]
                    risk = sl - price
                    tp1 = price - risk * 2
                    tp2 = price - risk * 3

                    return {
                        "side": "SELL",
                        "entry": price,
                        "sl": sl,
                        "tp1": tp1,
                        "tp2": tp2,
                        "rr": "1:3"
                    }

        return None