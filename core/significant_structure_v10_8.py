from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class SignificantStructureConfigV10_8:
    lookback_bars: int = 60
    cluster_atr: float = 0.12
    minimum_cluster_bps: float = 2.0
    minimum_prominence_atr: float = 0.50
    repeated_touches: int = 2
    neighbor_bars: int = 3

    def __post_init__(self) -> None:
        if self.lookback_bars < 10:
            raise ValueError("lookback_bars must be at least ten")
        if self.cluster_atr <= 0 or self.minimum_cluster_bps <= 0:
            raise ValueError("cluster tolerances must be positive")
        if self.minimum_prominence_atr <= 0:
            raise ValueError("minimum prominence must be positive")
        if self.repeated_touches < 2 or self.neighbor_bars < 1:
            raise ValueError("invalid touch or neighbor requirement")


@dataclass(frozen=True)
class SignificantLevelV10_8:
    price: float
    touches: int
    maximum_prominence_atr: float
    first_time: int
    last_time: int
    accepted_by: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignificantStructureSelectorV10_8:
    """Reduce noisy confirmed pivots into causal, significant price zones."""

    def __init__(self, config: SignificantStructureConfigV10_8 | None = None) -> None:
        self.config = config or SignificantStructureConfigV10_8()
        self.last_diagnostics: list[dict[str, Any]] = []

    def select(
        self,
        *,
        side: str,
        candles: list[dict[str, Any]],
        points: Iterable[dict[str, Any]],
        decision_time: int,
        atr14: float | None,
    ) -> tuple[float, ...]:
        side = str(side).upper()
        if side not in {"LONG", "SHORT"}:
            raise ValueError(f"invalid side: {side}")
        if not candles:
            self.last_diagnostics = []
            return ()
        recent = candles[-self.config.lookback_bars :]
        cutoff = int(recent[0]["time"])
        close = float(recent[-1]["close"])
        atr = float(atr14 or 0.0)
        if atr <= 0:
            atr = max(close * 0.001, 1e-12)
        tolerance = max(
            atr * self.config.cluster_atr,
            close * self.config.minimum_cluster_bps / 10_000.0,
        )
        index_by_time = {int(item["time"]): index for index, item in enumerate(candles)}
        observations: list[dict[str, Any]] = []
        for point in points:
            point_time = int(point["time"])
            if point_time < cutoff or int(point["confirmed_at"]) > int(decision_time):
                continue
            index = index_by_time.get(point_time)
            if index is None:
                continue
            start = max(0, index - self.config.neighbor_bars)
            end = min(len(candles), index + self.config.neighbor_bars + 1)
            neighbors = [
                candles[item_index]
                for item_index in range(start, end)
                if item_index != index
                and int(candles[item_index].get("close_time", candles[item_index]["time"]))
                <= int(decision_time)
            ]
            price = float(point["price"])
            if not neighbors:
                prominence = 0.0
            elif side == "LONG":
                prominence = max(0.0, price - max(float(item["high"]) for item in neighbors))
            else:
                prominence = max(0.0, min(float(item["low"]) for item in neighbors) - price)
            observations.append(
                {
                    "price": price,
                    "time": point_time,
                    "prominence_atr": prominence / atr,
                }
            )

        observations.sort(key=lambda item: float(item["price"]))
        clusters: list[list[dict[str, Any]]] = []
        for item in observations:
            if not clusters:
                clusters.append([item])
                continue
            center = sum(float(entry["price"]) for entry in clusters[-1]) / len(clusters[-1])
            if abs(float(item["price"]) - center) <= tolerance:
                clusters[-1].append(item)
            else:
                clusters.append([item])

        accepted: list[SignificantLevelV10_8] = []
        diagnostics: list[dict[str, Any]] = []
        for cluster in clusters:
            touches = len(cluster)
            prominence = max(float(item["prominence_atr"]) for item in cluster)
            repeated = touches >= self.config.repeated_touches
            prominent = prominence >= self.config.minimum_prominence_atr
            accepted_by = "TOUCHES" if repeated else "PROMINENCE" if prominent else "REJECTED_MINOR"
            item = SignificantLevelV10_8(
                price=sum(float(entry["price"]) for entry in cluster) / touches,
                touches=touches,
                maximum_prominence_atr=prominence,
                first_time=min(int(entry["time"]) for entry in cluster),
                last_time=max(int(entry["time"]) for entry in cluster),
                accepted_by=accepted_by,
            )
            diagnostics.append(item.as_dict())
            if repeated or prominent:
                accepted.append(item)
        self.last_diagnostics = diagnostics
        return tuple(sorted(item.price for item in accepted))
