from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProfitProtectionConfigV10_4:
    """Frozen all-in-R profit protection for the paper portfolio."""

    arm_net_r: float = 0.50
    minimum_locked_net_r: float = 0.10
    trailing_giveback_r: float = 0.40

    def __post_init__(self) -> None:
        if self.arm_net_r <= 0.0:
            raise ValueError("arm_net_r must be positive")
        if self.minimum_locked_net_r <= 0.0:
            raise ValueError("minimum_locked_net_r must be positive")
        if self.trailing_giveback_r <= 0.0:
            raise ValueError("trailing_giveback_r must be positive")
        if self.minimum_locked_net_r >= self.arm_net_r:
            raise ValueError("minimum lock must be below the arming threshold")


class ProfitProtectionV10_4:
    """Track peak all-in net R and signal a causal profit-protection exit.

    The guard is evaluated on observed aggregate trades. It never predicts a
    reversal and never treats candle colour as an exit. After the trade reaches
    the arming threshold, the protected floor can only tighten.
    """

    def __init__(
        self,
        config: ProfitProtectionConfigV10_4 | None = None,
    ) -> None:
        self.config = config or ProfitProtectionConfigV10_4()
        self.reset()

    def reset(self) -> None:
        self.entry_event_time: int | None = None
        self.side: str | None = None
        self.peak_net_r: float | None = None
        self.floor_net_r: float | None = None
        self.armed = False
        self.last_net_r: float | None = None

    def _reset_for_position(self, position: dict[str, Any]) -> None:
        self.entry_event_time = int(position["entry_event_time"])
        self.side = str(position["position"])
        self.peak_net_r = None
        self.floor_net_r = None
        self.armed = False
        self.last_net_r = None

    def observe(self, position: dict[str, Any]) -> dict[str, Any]:
        entry_event_time = int(position["entry_event_time"])
        if self.entry_event_time != entry_event_time:
            self._reset_for_position(position)

        risk = float(position.get("planned_stop_loss", 0.0))
        if risk <= 0.0:
            raise ValueError("position planned_stop_loss must be positive")
        net_r = float(position.get("current_pnl", 0.0)) / risk
        self.last_net_r = net_r
        self.peak_net_r = (
            net_r if self.peak_net_r is None else max(self.peak_net_r, net_r)
        )

        if self.peak_net_r >= self.config.arm_net_r:
            self.armed = True
            candidate_floor = max(
                self.config.minimum_locked_net_r,
                self.peak_net_r - self.config.trailing_giveback_r,
            )
            self.floor_net_r = (
                candidate_floor
                if self.floor_net_r is None
                else max(self.floor_net_r, candidate_floor)
            )

        # A discontinuous price jump can cross the floor and already be
        # negative. Do not mislabel that as a protected-profit exit; the
        # original stop/reversal logic remains responsible for it.
        should_exit = bool(
            self.armed
            and self.floor_net_r is not None
            and 0.0 < net_r <= self.floor_net_r
        )
        result = self.snapshot()
        result["should_exit"] = should_exit
        return result

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": "V10.4",
            "entry_event_time": self.entry_event_time,
            "side": self.side,
            "armed": self.armed,
            "peak_net_r": self.peak_net_r,
            "floor_net_r": self.floor_net_r,
            "last_net_r": self.last_net_r,
            "config": asdict(self.config),
        }
