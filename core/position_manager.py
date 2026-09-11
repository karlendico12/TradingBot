# ==========================================================
# POSITION MANAGER
# TradingBot V8
# ==========================================================


class PositionManager:

    def __init__(self):

        # ==================================================
        # CURRENT POSITION
        # ==================================================

        self.position = None

        # ==================================================
        # REALIZED TOTAL P/L
        # ==================================================

        self.total_pnl = 0.0

        # ==================================================
        # LAST CLOSED TRADE
        # ==================================================

        self.last_trade = None

        # ==================================================
        # LAST ENTRY CANDLE
        # Prevent multiple entries on same candle
        # ==================================================

        self.last_entry_candle = None

    # ==========================================================
    # GET POSITION
    # ==========================================================

    def get_position(self):

        return self.position

    # ==========================================================
    # HAS POSITION
    # ==========================================================

    def has_position(self):

        return self.position is not None

    # ==========================================================
    # GET TOTAL REALIZED P/L
    # ==========================================================

    def get_total_pnl(self):

        return float(self.total_pnl)

    # ==========================================================
    # GET UNREALIZED P/L
    # ==========================================================

    def get_unrealized_pnl(self):

        if self.position is None:
            return 0.0

        return float(
            self.position.get(
                "current_pnl",
                0.0
            )
        )

    # ==========================================================
    # GET P/L PERCENT
    # ==========================================================

    def get_pnl_percent(self):

        if self.position is None:
            return 0.0

        return float(
            self.position.get(
                "pnl_percent",
                0.0
            )
        )

    # ==========================================================
    # GET LAST TRADE
    # ==========================================================

    def get_last_trade(self):

        return self.last_trade

    # ==========================================================
    # CHECK ENTRY
    # ==========================================================

    def can_enter(
        self,
        signal,
        candle_time,
    ):

        # ==================================================
        # INVALID SIGNAL
        # ==================================================

        if signal not in (
            "LONG",
            "SHORT",
        ):

            return (
                False,
                "Invalid signal"
            )

        # ==================================================
        # NO POSITION
        # ==================================================

        if self.position is None:

            if (
                self.last_entry_candle
                == candle_time
            ):

                return (
                    False,
                    "Already entered this candle"
                )

            return (
                True,
                "Entry allowed"
            )

        # ==================================================
        # CURRENT POSITION
        # ==================================================

        current_side = (
            self.position["position"]
        )

        # ==================================================
        # SAME DIRECTION
        # ==================================================

        if current_side == signal:

            return (
                False,
                f"Already in {signal}"
            )

        # ==================================================
        # OPPOSITE DIRECTION
        # REVERSAL IS ALLOWED
        # ==================================================

        if (
            self.last_entry_candle
            == candle_time
        ):

            return (
                False,
                "Already entered this candle"
            )

        return (
            True,
            "Reversal allowed"
        )

    # ==========================================================
    # OPEN POSITION
    # ==========================================================

    def open_position(
        self,
        signal,
        entry_price,
        stop_loss,
        take_profit,
        quantity,
        candle_time,
    ):

        # ==================================================
        # VALIDATE SIGNAL
        # ==================================================

        if signal not in (
            "LONG",
            "SHORT",
        ):

            raise ValueError(
                f"Invalid position signal: {signal}"
            )

        # ==================================================
        # CONVERT VALUES
        # ==================================================

        entry_price = float(entry_price)
        stop_loss = float(stop_loss)
        take_profit = float(take_profit)
        quantity = float(quantity)

        if entry_price <= 0:
            raise ValueError(
                "Entry price must be greater than zero"
            )

        if quantity <= 0:
            raise ValueError(
                "Quantity must be greater than zero"
            )

        # ==================================================
        # CREATE POSITION
        # ==================================================

        self.position = {

            "position": signal,

            "entry": entry_price,

            "stop_loss": stop_loss,

            "take_profit": take_profit,

            "quantity": quantity,

            "candle_time": candle_time,

            # ==============================================
            # CURRENT MARKET PRICE
            # ==============================================

            "current_price": entry_price,

            # ==============================================
            # UNREALIZED P/L
            # ==============================================

            "current_pnl": 0.0,

            # ==============================================
            # UNREALIZED P/L %
            # ==============================================

            "pnl_percent": 0.0,
        }

        # ==================================================
        # REMEMBER ENTRY CANDLE
        # ==================================================

        self.last_entry_candle = candle_time

        return self.position

    # ==========================================================
    # UPDATE UNREALIZED P/L
    # ==========================================================

    def update_unrealized_pnl(
        self,
        current_price,
    ):

        if self.position is None:

            return None

        current_price = float(
            current_price
        )

        if current_price <= 0:

            return self.position

        # ==================================================
        # POSITION DATA
        # ==================================================

        entry = float(
            self.position["entry"]
        )

        quantity = float(
            self.position["quantity"]
        )

        side = (
            self.position["position"]
        )

        # ==================================================
        # CALCULATE P/L
        # ==================================================

        if side == "LONG":

            pnl = (
                current_price
                - entry
            ) * quantity

        elif side == "SHORT":

            pnl = (
                entry
                - current_price
            ) * quantity

        else:

            pnl = 0.0

        # ==================================================
        # CALCULATE P/L %
        #
        # Based on position notional:
        #
        # entry price × quantity
        # ==================================================

        position_value = (
            entry * quantity
        )

        if position_value > 0:

            pnl_percent = (
                pnl / position_value
            ) * 100.0

        else:

            pnl_percent = 0.0

        # ==================================================
        # STORE CURRENT PRICE
        # ==================================================

        self.position[
            "current_price"
        ] = current_price

        # ==================================================
        # STORE UNREALIZED P/L
        # ==================================================

        self.position[
            "current_pnl"
        ] = float(pnl)

        # ==================================================
        # STORE P/L %
        # ==================================================

        self.position[
            "pnl_percent"
        ] = float(pnl_percent)

        return self.position

    # ==========================================================
    # CHECK EXIT
    # ==========================================================

    def check_exit(
        self,
        current_price,
    ):

        if self.position is None:

            return None

        current_price = float(
            current_price
        )

        side = (
            self.position["position"]
        )

        stop_loss = float(
            self.position["stop_loss"]
        )

        take_profit = float(
            self.position["take_profit"]
        )

        # ==================================================
        # LONG EXIT
        # ==================================================

        if side == "LONG":

            # ==============================================
            # STOP LOSS
            # ==============================================

            if current_price <= stop_loss:

                return self.close_position(
                    exit_price=current_price,
                    reason="STOP LOSS",
                )

            # ==============================================
            # TAKE PROFIT
            # ==============================================

            if current_price >= take_profit:

                return self.close_position(
                    exit_price=current_price,
                    reason="TAKE PROFIT",
                )

        # ==================================================
        # SHORT EXIT
        # ==================================================

        elif side == "SHORT":

            # ==============================================
            # STOP LOSS
            # ==============================================

            if current_price >= stop_loss:

                return self.close_position(
                    exit_price=current_price,
                    reason="STOP LOSS",
                )

            # ==============================================
            # TAKE PROFIT
            # ==============================================

            if current_price <= take_profit:

                return self.close_position(
                    exit_price=current_price,
                    reason="TAKE PROFIT",
                )

        return None

    # ==========================================================
    # CLOSE POSITION
    # ==========================================================

    def close_position(
        self,
        exit_price,
        reason,
    ):

        if self.position is None:

            return None

        exit_price = float(
            exit_price
        )

        # ==================================================
        # COPY POSITION DATA
        # ==================================================

        position = self.position

        side = (
            position["position"]
        )

        entry = float(
            position["entry"]
        )

        quantity = float(
            position["quantity"]
        )

        # ==================================================
        # CALCULATE REALIZED P/L
        # ==================================================

        if side == "LONG":

            pnl = (
                exit_price
                - entry
            ) * quantity

        elif side == "SHORT":

            pnl = (
                entry
                - exit_price
            ) * quantity

        else:

            pnl = 0.0

        pnl = float(pnl)

        # ==================================================
        # CALCULATE REALIZED P/L %
        # ==================================================

        position_value = (
            entry * quantity
        )

        if position_value > 0:

            pnl_percent = (
                pnl / position_value
            ) * 100.0

        else:

            pnl_percent = 0.0

        # ==================================================
        # ADD TO TOTAL REALIZED P/L
        # ==================================================

        self.total_pnl += pnl

        self.total_pnl = float(
            self.total_pnl
        )

        # ==================================================
        # CREATE CLOSED TRADE
        # ==================================================

        closed_trade = {

            "position": side,

            "entry": entry,

            "exit": exit_price,

            "quantity": quantity,

            "pnl": pnl,

            "pnl_percent": float(
                pnl_percent
            ),

            "reason": reason,

            "candle_time": position.get(
                "candle_time"
            ),
        }

        # ==================================================
        # STORE LAST TRADE
        # ==================================================

        self.last_trade = (
            closed_trade
        )

        # ==================================================
        # CLEAR CURRENT POSITION
        # ==================================================

        self.position = None

        # ==================================================
        # RETURN CLOSED TRADE
        # ==================================================

        return closed_trade

    # ==========================================================
    # RESET
    # ==========================================================

    def reset(self):

        self.position = None

        self.total_pnl = 0.0

        self.last_trade = None

        self.last_entry_candle = None