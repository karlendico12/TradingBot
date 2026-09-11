class RiskManager:

    def __init__(
        self,
        account_balance=1000.0,
        risk_percent=1.0,
        stop_loss_percent=0.002,
        reward_ratio=2.0
    ):
        self.account_balance = account_balance
        self.risk_percent = risk_percent
        self.stop_loss_percent = stop_loss_percent
        self.reward_ratio = reward_ratio

    # Original method (kept)
    def calculate(self, signal, entry_price):

        if signal not in ("LONG", "SHORT"):
            return {
                "valid": False,
                "signal": signal,
                "reason": "No trade signal"
            }

        entry_price = float(entry_price)

        risk_amount = (
            self.account_balance
            * self.risk_percent
            / 100
        )

        if signal == "LONG":

            stop_loss = (
                entry_price
                * (1 - self.stop_loss_percent)
            )

            risk_per_unit = (
                entry_price - stop_loss
            )

            take_profit = (
                entry_price
                + (
                    risk_per_unit
                    * self.reward_ratio
                )
            )

        else:

            stop_loss = (
                entry_price
                * (1 + self.stop_loss_percent)
            )

            risk_per_unit = (
                stop_loss - entry_price
            )

            take_profit = (
                entry_price
                - (
                    risk_per_unit
                    * self.reward_ratio
                )
            )

        if risk_per_unit <= 0:

            return {
                "valid": False,
                "signal": signal,
                "reason": "Invalid risk calculation"
            }

        quantity = (
            risk_amount
            / risk_per_unit
        )

        return {
            "valid": True,
            "signal": signal,
            "entry": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": risk_amount,
            "risk_per_unit": risk_per_unit,
            "quantity": quantity,
            "reward_ratio": self.reward_ratio
        }

    # V8 compatibility
    def calculate_position(self, signal, entry_price):

        result = self.calculate(signal, entry_price)

        if not result["valid"]:
            return None

        return {
            "stop_loss": result["stop_loss"],
            "take_profit": result["take_profit"],
            "quantity": result["quantity"],
            "risk_amount": result["risk_amount"],
            "entry": result["entry"],
            "signal": result["signal"]
        }