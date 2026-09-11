class TradeDecisionEngine:
    def __init__(self):
        self.last_signal = None

    def evaluate(
        self,
        price,
        trend,
        bos_signal,
        sweep_signal,
        fvg_zones,
        order_blocks
    ):
        score_buy = 0
        score_sell = 0
        reasons = []

        # Trend
        if trend == "bullish":
            score_buy += 2
            reasons.append("Bullish Trend")
        elif trend == "bearish":
            score_sell += 2
            reasons.append("Bearish Trend")

        # BOS
        if bos_signal:
            if bos_signal["type"] == "bullish":
                score_buy += 3
                reasons.append("Bullish BOS")
            else:
                score_sell += 3
                reasons.append("Bearish BOS")

        # Liquidity Sweep
        if sweep_signal:
            if sweep_signal["side"] == "BUY":
                score_buy += 2
                reasons.append("Bearish Liquidity Sweep")
            else:
                score_sell += 2
                reasons.append("Bullish Liquidity Sweep")

        # FVG
        for zone in reversed(fvg_zones):
            if zone["bottom"] <= price <= zone["top"]:
                if zone["type"] == "bullish":
                    score_buy += 1
                    reasons.append("Inside Bullish FVG")
                else:
                    score_sell += 1
                    reasons.append("Inside Bearish FVG")
                break

        # Order Block
        for block in reversed(order_blocks):
            if block["bottom"] <= price <= block["top"]:
                if block["type"] == "bullish":
                    score_buy += 2
                    reasons.append("Inside Bullish Order Block")
                else:
                    score_sell += 2
                    reasons.append("Inside Bearish Order Block")
                break

        if score_buy >= 7 and score_buy > score_sell:
            signal = "BUY"
        elif score_sell >= 7 and score_sell > score_buy:
            signal = "SELL"
        else:
            signal = None

        if signal and signal != self.last_signal:
            self.last_signal = signal

            risk = price * 0.002  # 0.2%

            if signal == "BUY":
                return {
                    "side": signal,
                    "entry": price,
                    "sl": price - risk,
                    "tp1": price + risk * 2,
                    "tp2": price + risk * 3,
                    "score": score_buy,
                    "reasons": reasons
                }

            return {
                "side": signal,
                "entry": price,
                "sl": price + risk,
                "tp1": price - risk * 2,
                "tp2": price - risk * 3,
                "score": score_sell,
                "reasons": reasons
            }

        return None