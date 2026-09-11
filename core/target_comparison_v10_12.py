"""Independent forward paper portfolios; only target selection differs.

The factory supplies the existing complete V10.12 execution implementation.
No comparison terminal starts a feed, worker, window, or actual paper order.
"""
from __future__ import annotations

import inspect
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from core.entry_policy_v10_5 import StructuralTargetPlannerV10_5


class UncappedTargetPlannerV10_12(StructuralTargetPlannerV10_5):
    """Keep structure, its ATR buffer, costs and fixed target; omit ATR ceiling.

    This is an experimental policy, not a forecast that fixed 2R is attainable.
    As in the baseline, only caller-supplied confirmed significant levels count.
    """

    def evaluate(self, side, market_price, execution, *, atr14, opposing_levels=()):
        return super().evaluate(
            side, market_price, execution, atr14=atr14,
            opposing_levels=opposing_levels, include_atr_cap=False,
        )


class ResearchWindow:
    """Discard GUI signals; the comparison has no user-visible trading window."""
    def __getattr__(self, name):
        if name.startswith("update_"):
            return lambda *args: None
        raise AttributeError(name)


class TargetComparisonV10_12:
    revision = "TARGET_CAP_COMPARISON_1"
    forwarded = {
        "trade_callback", "price_callback", "candle_callback", "history_callback",
        "history_complete_callback", "funding_callback", "book_callback",
    }

    def __init__(self, root: Path, factory, audit) -> None:
        self.audit = audit
        self.failed = False
        self.stopped = False
        self.portfolios = {}
        for mode in ("BASELINE", "NO_ATR_CAP"):
            portfolio = factory(root / mode.lower(), mode)
            self.portfolios[mode] = portfolio
        self.callbacks = {mode: p.market_callbacks() for mode, p in self.portfolios.items()}
        self.audit.record(
            "TARGET_COMPARISON_STARTED", self.revision, event_time=int(time.time() * 1000),
            details={"modes": list(self.portfolios), "root": str(root),
                     "actual_policy": "BASELINE", "independent_equity": True},
        )

    def seed(self, candles) -> None:
        for portfolio in self.portfolios.values():
            portfolio.micro_bars.seed(deepcopy(candles))
            portfolio.micro_history_seeded = bool(candles)

    async def dispatch(self, name: str, *args: Any, **kwargs: Any) -> None:
        if self.failed or self.stopped:
            return
        try:
            for mode in self.portfolios:
                result = self.callbacks[mode][name](*deepcopy(args), **deepcopy(kwargs))
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:
            # Research failure must neither open actual orders nor break the feed.
            self.failed = True
            self.audit.record(
                "TARGET_COMPARISON_FAILED", type(exc).__name__,
                event_time=int(time.time() * 1000),
                details={"callback": name, "error": str(exc), "revision": self.revision},
            )
            print(f"[TARGET COMPARISON] DISABLED: {type(exc).__name__}: {exc}", flush=True)

    async def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        errors = []
        for mode, portfolio in self.portfolios.items():
            try:
                await portfolio.stop()
            except Exception as exc:
                errors.append(f"{mode}: {type(exc).__name__}: {exc}")
        if errors:
            self.audit.record("TARGET_COMPARISON_FAILED", "SHUTDOWN_ERROR",
                              event_time=int(time.time() * 1000), details={"errors": errors})
