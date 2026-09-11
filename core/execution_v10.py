from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionConfig:
    """Frozen V10 paper-execution and risk assumptions."""

    starting_balance: float = 1_000.0
    risk_percent: float = 1.0
    stop_loss_percent: float = 0.002
    reward_ratio: float = 2.0
    max_notional_multiple: float = 3.0
    fee_rate: float = 0.0004
    slippage_bps: float = 1.0
    max_entry_delay_ms: int = 5_000

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000.0


def candle_entry_is_timely(
    candle: dict[str, Any],
    max_delay_ms: int,
    *,
    now_ms: int | None = None,
) -> bool:
    """Allow an entry only from a genuinely near-live completed decision."""
    close_time = int(candle.get("close_time", candle.get("time", 0)))
    if now_ms is None:
        import time

        now_ms = int(time.time() * 1000)
    age_ms = int(now_ms) - close_time
    # Apply the wall-clock gate to WebSocket and REST candles alike. A queued
    # WebSocket close plus queued trade must not create a retroactive entry.
    # Permit a small exchange/local-clock skew, but never historical delivery.
    return -1_000 <= age_ms <= int(max_delay_ms)


@dataclass(frozen=True)
class PendingEntry:
    signal: str
    candle_time: int
    decision_time_ms: int

    def status(self, event_time_ms: int, max_delay_ms: int) -> str:
        # A fill must be strictly later than the completed-candle decision.
        if event_time_ms <= self.decision_time_ms:
            return "TOO_EARLY"
        if event_time_ms - self.decision_time_ms > max_delay_ms:
            return "EXPIRED"
        return "ELIGIBLE"


class PaperPositionManagerV10:
    """Single-position paper ledger with adverse fills and all-in net P/L."""

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        realized_net_pnl: float = 0.0,
    ) -> None:
        self.config = config or ExecutionConfig()
        self.realized_net_pnl = float(realized_net_pnl)
        self.position: dict[str, Any] | None = None
        self.last_entry_candle: int | None = None

    @property
    def equity(self) -> float:
        return max(
            0.0,
            float(self.config.starting_balance + self.realized_net_pnl),
        )

    def get_position(self) -> dict[str, Any] | None:
        return self.position

    def has_position(self) -> bool:
        return self.position is not None

    def get_total_pnl(self) -> float:
        return float(self.realized_net_pnl)

    def get_unrealized_pnl(self) -> float:
        if self.position is None:
            return 0.0
        return float(self.position.get("current_pnl", 0.0))

    def _entry_fill(self, signal: str, market_price: float) -> float:
        slip = self.config.slippage_rate
        if signal == "LONG":
            return market_price * (1.0 + slip)
        return market_price * (1.0 - slip)

    def _exit_fill(self, side: str, market_price: float) -> float:
        slip = self.config.slippage_rate
        if side == "LONG":
            return market_price * (1.0 - slip)
        return market_price * (1.0 + slip)

    def open_position(
        self,
        signal: str,
        market_price: float,
        candle_time: int,
        event_time_ms: int,
        execution_source: str = "UNKNOWN",
    ) -> dict[str, Any]:
        if self.position is not None:
            raise RuntimeError("Cannot open while another position is active")
        if signal not in {"LONG", "SHORT"}:
            raise ValueError(f"Invalid signal: {signal}")

        market_price = float(market_price)
        if market_price <= 0:
            raise ValueError("Market price must be positive")

        entry_fill = self._entry_fill(signal, market_price)
        stop_distance = entry_fill * self.config.stop_loss_percent

        if signal == "LONG":
            stop_loss = entry_fill - stop_distance
            take_profit = entry_fill + stop_distance * self.config.reward_ratio
        else:
            stop_loss = entry_fill + stop_distance
            take_profit = entry_fill - stop_distance * self.config.reward_ratio

        stop_fill = self._exit_fill(signal, stop_loss)
        price_loss_per_unit = abs(entry_fill - stop_fill)
        fee_loss_per_unit = self.config.fee_rate * (entry_fill + stop_fill)
        total_loss_per_unit = price_loss_per_unit + fee_loss_per_unit
        if total_loss_per_unit <= 0:
            raise ValueError("Invalid all-in stop risk")

        risk_budget = self.equity * self.config.risk_percent / 100.0
        quantity_by_risk = risk_budget / total_loss_per_unit
        max_notional = self.equity * self.config.max_notional_multiple
        quantity_by_notional = max_notional / entry_fill
        quantity = min(quantity_by_risk, quantity_by_notional)
        if quantity <= 0:
            raise ValueError("Calculated quantity must be positive")

        entry_fee = entry_fill * quantity * self.config.fee_rate
        planned_stop_loss = total_loss_per_unit * quantity
        notional = entry_fill * quantity

        self.position = {
            "version": 10,
            "position": signal,
            "candle_time": int(candle_time),
            "entry_event_time": int(event_time_ms),
            "entry_source": str(execution_source),
            "entry_market": market_price,
            "entry": entry_fill,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "quantity": quantity,
            "entry_fee": entry_fee,
            "funding_pnl": 0.0,
            "notional": notional,
            "risk_budget": risk_budget,
            "planned_stop_loss": planned_stop_loss,
            "current_price": market_price,
            "current_pnl": -entry_fee,
            "pnl_percent": (-entry_fee / notional * 100.0) if notional else 0.0,
            "execution_config": asdict(self.config),
            "metadata": {},
        }
        self.last_entry_candle = int(candle_time)
        return self.position

    def update_unrealized_pnl(self, market_price: float) -> dict[str, Any] | None:
        if self.position is None:
            return None

        market_price = float(market_price)
        side = str(self.position["position"])
        entry_fill = float(self.position["entry"])
        quantity = float(self.position["quantity"])
        exit_fill = self._exit_fill(side, market_price)

        if side == "LONG":
            gross_pnl = (exit_fill - entry_fill) * quantity
        else:
            gross_pnl = (entry_fill - exit_fill) * quantity

        exit_fee = exit_fill * quantity * self.config.fee_rate
        net_pnl = (
            gross_pnl
            - float(self.position["entry_fee"])
            - exit_fee
            + float(self.position.get("funding_pnl", 0.0))
        )
        notional = float(self.position["notional"])
        self.position["current_price"] = market_price
        self.position["current_pnl"] = net_pnl
        self.position["pnl_percent"] = (
            net_pnl / notional * 100.0 if notional else 0.0
        )
        return self.position

    def check_exit(
        self,
        market_price: float,
        event_time_ms: int,
        execution_source: str = "UNKNOWN",
    ) -> dict[str, Any] | None:
        if self.position is None:
            return None

        market_price = float(market_price)
        side = str(self.position["position"])
        stop_loss = float(self.position["stop_loss"])
        take_profit = float(self.position["take_profit"])

        if side == "LONG":
            if market_price <= stop_loss:
                return self.close_position(
                    market_price, "STOP LOSS", event_time_ms, execution_source
                )
            if market_price >= take_profit:
                return self.close_position(
                    market_price, "TAKE PROFIT", event_time_ms, execution_source
                )
        else:
            if market_price >= stop_loss:
                return self.close_position(
                    market_price, "STOP LOSS", event_time_ms, execution_source
                )
            if market_price <= take_profit:
                return self.close_position(
                    market_price, "TAKE PROFIT", event_time_ms, execution_source
                )
        return None

    def apply_funding(
        self,
        funding_time_ms: int,
        funding_rate: float,
        mark_price: float,
    ) -> float:
        if self.position is None:
            return 0.0
        if int(funding_time_ms) <= int(self.position["entry_event_time"]):
            return 0.0

        applied = self.position.setdefault("applied_funding_times", [])
        if int(funding_time_ms) in applied:
            return 0.0

        notional = float(mark_price) * float(self.position["quantity"])
        signed_payment = notional * float(funding_rate)
        funding_pnl = -signed_payment if self.position["position"] == "LONG" else signed_payment
        self.position["funding_pnl"] = (
            float(self.position.get("funding_pnl", 0.0)) + funding_pnl
        )
        applied.append(int(funding_time_ms))
        return float(funding_pnl)

    def close_position(
        self,
        market_price: float,
        reason: str,
        event_time_ms: int,
        execution_source: str = "UNKNOWN",
    ) -> dict[str, Any] | None:
        if self.position is None:
            return None

        position = self.position
        side = str(position["position"])
        market_price = float(market_price)
        exit_fill = self._exit_fill(side, market_price)
        entry_fill = float(position["entry"])
        quantity = float(position["quantity"])

        if side == "LONG":
            gross_pnl = (exit_fill - entry_fill) * quantity
        else:
            gross_pnl = (entry_fill - exit_fill) * quantity

        exit_fee = exit_fill * quantity * self.config.fee_rate
        total_fees = float(position["entry_fee"]) + exit_fee
        funding_pnl = float(position.get("funding_pnl", 0.0))
        net_pnl = gross_pnl - total_fees + funding_pnl
        self.realized_net_pnl += net_pnl

        trade = {
            "version": 10,
            "position": side,
            "candle_time": int(position["candle_time"]),
            "entry_event_time": int(position["entry_event_time"]),
            "entry_source": str(position.get("entry_source", "UNKNOWN")),
            "exit_event_time": int(event_time_ms),
            "exit_source": str(execution_source),
            "entry_market": float(position["entry_market"]),
            "entry": entry_fill,
            "exit_market": market_price,
            "exit": exit_fill,
            "quantity": quantity,
            "reason": str(reason),
            "gross_pnl": gross_pnl,
            "fees": total_fees,
            "funding_pnl": funding_pnl,
            "pnl": net_pnl,
            "net_pnl": net_pnl,
            "balance_after": self.equity,
            "metadata": dict(position.get("metadata", {})),
        }
        self.position = None
        return trade
