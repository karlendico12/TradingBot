"""Read-only V10.12 execution audit; never starts a bot or creates a database."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read_rows(path: Path, table: str) -> list[dict]:
    if not path.is_file():
        return []
    # Callers supply fixed table names, never user SQL.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
    finally:
        connection.close()


def utc(milliseconds):
    return None if milliseconds is None else datetime.fromtimestamp(
        milliseconds / 1000, tz=timezone.utc).isoformat(timespec="milliseconds")


def collect(runtime: Path) -> dict:
    events = read_rows(runtime / "policy_audit_v10_5.sqlite3", "policy_events")
    trades = read_rows(runtime / "paper_v10.sqlite3", "trades")
    active = read_rows(runtime / "paper_v10.sqlite3", "active_position")
    context = read_rows(runtime / "diagnostics_v10_1.sqlite3", "decisions")
    relevant = [e for e in events if e["event_type"].startswith(
        ("MICRO_", "EARLY_FLOW_", "FAST_ENTRY_", "STRUCTURAL_TARGET_", "EVIDENCE_", "TARGET_"))]
    funnel = Counter(f"{e['event_type']} / {e['reason']}" for e in relevant)
    attempts = []
    for event in relevant:
        if event["event_type"] not in {"FAST_ENTRY_ACCEPTED", "FAST_ENTRY_REJECTED"}:
            continue
        details = json.loads(event["details_json"])
        watch = details.get("watch", {})
        evaluation = details.get("target_evaluation", {})
        trigger_flow = details.get("trigger_flow", {})
        decision = watch.get("decision_time")
        attempt = {
            "audit_id": event["id"], "side": event["side"],
            "outcome": event["event_type"], "reason": event["reason"],
            "decision_utc": utc(decision),
            "flow_started_utc": utc(watch.get("first_confirmed_time")),
            "trigger_utc": utc(event["event_time"]),
            "decision_to_trigger_ms": None if decision is None else event["event_time"] - decision,
            "room_bps": evaluation.get("room_bps"),
            "estimated_net_reward_r": evaluation.get("estimated_net_reward_r"),
            "target_source": evaluation.get("target_source"),
            "diagnostics": trigger_flow.get("v10_12_diagnostics"),
        }
        attempts.append(attempt)
    closed = []
    for trade in trades:
        metadata = json.loads(trade.get("metadata_json", "{}"))
        entry = metadata.get("v10_12_early_flow_entry", {})
        watch = entry.get("watch", {})
        trigger_flow = entry.get("trigger_flow", {})
        closed.append({
            "id": trade["id"], "side": trade["side"], "reason": trade["reason"],
            "entry_utc": utc(trade["entry_event_time"]),
            "exit_utc": utc(trade["exit_event_time"]),
            "decision_to_fill_ms": (trade["entry_event_time"] - watch["decision_time"]
                                    if "decision_time" in watch else metadata.get("entry_latency_ms")),
            "holding_ms": trade["exit_event_time"] - trade["entry_event_time"],
            "gross_pnl": trade["gross_pnl"], "fees": trade["fees"],
            "funding_pnl": trade["funding_pnl"], "net_pnl": trade["net_pnl"],
            "path": metadata.get("path"),
            "revision": trigger_flow.get("v10_12_diagnostics", {}).get("revision", "legacy / untagged"),
        })
    revision_totals = {}
    for trade in closed:
        summary = revision_totals.setdefault(trade["revision"], {"trades": 0, "net_pnl": 0.0})
        summary["trades"] += 1
        summary["net_pnl"] += trade["net_pnl"]
    return {
        "runtime": str(runtime.resolve()),
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "missing_databases": [name for name in ("policy_audit_v10_5.sqlite3", "paper_v10.sqlite3", "diagnostics_v10_1.sqlite3") if not (runtime / name).is_file()],
        "context_decisions": len(context),
        "latest_context_utc": utc(max((r["decision_time"] for r in context), default=None)),
        "latest_micro_utc": utc(max((e["event_time"] for e in relevant if e["event_type"] == "MICRO_DECISION"), default=None)),
        "funnel": dict(sorted(funnel.items())), "attempts": attempts,
        "latest_revision_configuration": next((json.loads(e["details_json"]) for e in reversed(events)
                                                if e["event_type"] == "EARLY_FLOW_REVISION"), None),
        "closed_trades": closed, "active_positions": len(active),
        "totals": {"trades": len(trades), "wins": sum(t["net_pnl"] > 0 for t in trades),
                   **{key: sum(t[key] for t in trades) for key in ("gross_pnl", "fees", "funding_pnl", "net_pnl")}},
        "revision_totals": revision_totals,
        "recent_events": [{"utc": utc(e["event_time"]), "type": e["event_type"],
                           "reason": e["reason"], "details": json.loads(e["details_json"])} for e in relevant[-12:]],
    }


def render(data: dict) -> str:
    lines = ["V10.12 paper execution audit", f"Runtime: {data['runtime']}",
             f"Read at: {data['as_of_utc']}",
             "Times are UTC. Separate read-only database snapshots; live counts may advance.",
             "Policy: 10s watch / 500ms flow / 20 trades / 5bps chase; target gates 18bps / 0.35R.",
             "Code defaults: daily trade cap OFF; daily-loss gate SHADOW ONLY.",
             "These are code defaults, not a probe of the running process configuration.",
             f"3m contexts: {data['context_decisions']}; latest: {data['latest_context_utc']}",
             f"Latest completed 1m decision: {data['latest_micro_utc']}"]
    if data["missing_databases"]:
        lines.append("Missing databases: " + ", ".join(data["missing_databases"]))
    lines.append("Latest recorded startup configuration: " + json.dumps(data["latest_revision_configuration"]))
    lines.append("\nExecution funnel (MICRO arm is provisional; EARLY_FLOW arm replaces it):")
    lines.extend(f"  {name}: {count}" for name, count in data["funnel"].items())
    lines.append("\nRecent trigger attempts (last 20):")
    lines.extend("  " + json.dumps(attempt, sort_keys=True) for attempt in data["attempts"][-20:])
    lines.append("\nAfter-cost totals: " + json.dumps(data["totals"], sort_keys=True))
    lines.append("Gross P/L already includes fill slippage; fees and funding are separate.")
    lines.append(f"Active paper positions: {data['active_positions']}")
    lines.append("By entry diagnostic revision: " + json.dumps(data["revision_totals"]))
    lines.append("\nRecent closed trade traces (last 20):")
    lines.extend("  " + json.dumps(trade, sort_keys=True) for trade in data["closed_trades"][-20:])
    lines.append("\nRecent watch/exit events (last 12):")
    lines.extend("  " + json.dumps(event, sort_keys=True) for event in data["recent_events"])
    lines.append("\nLegacy records lack receipt/gap/adverse-watch diagnostics; missing values are unknown.")
    lines.append("V10.11 target fallback restrictions are unchanged, including ATR buffer and STRUCTURE-only selection.")
    lines.append("No matched counterfactual replay is available: these results cannot establish whether earlier entry improves net returns.")
    if "target_comparison" in data:
        lines.append("\nTARGET POLICY FORWARD COMPARISON (SHADOW ONLY; actual policy stays BASELINE)")
        lines.append(json.dumps(data["target_comparison"], indent=2))
        lines.append("Compare the two research ledgers, not old actual trades. Open/interrupted positions and comparison failures prevent a complete outcome comparison.")
    return "\n".join(lines)


def target_comparison_report(runtime: Path) -> dict:
    result = {}
    for mode in ("baseline", "no_atr_cap"):
        root = runtime / "target_comparison_v1" / mode
        data = collect(root)
        pnl = peak = drawdown = 0.0
        gains = losses = 0.0
        for trade in data["closed_trades"]:
            value = trade["net_pnl"]
            pnl += value
            peak = max(peak, pnl)
            drawdown = max(drawdown, peak - pnl)
            gains += max(value, 0.0)
            losses += max(-value, 0.0)
        interruptions = read_rows(root / "paper_v10.sqlite3", "interruptions")
        result[mode] = {
            "totals": data["totals"], "open_positions": data["active_positions"],
            "latest_micro_utc": data["latest_micro_utc"],
            "startup_configuration": data["latest_revision_configuration"],
            "interrupted_positions": len(interruptions),
            "closed_equity_drawdown": drawdown,
            "profit_factor": gains / losses if losses else None,
            "funnel": data["funnel"], "missing_databases": data["missing_databases"],
        }
    events = read_rows(runtime / "policy_audit_v10_5.sqlite3", "policy_events")
    result["lifecycle"] = [{"type": e["event_type"], "utc": utc(e["event_time"]),
                            "reason": e["reason"]} for e in events
                           if e["event_type"].startswith("TARGET_COMPARISON_")]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=Path(__file__).resolve().parent / "runtime_v10_12")
    parser.add_argument("--json", action="store_true", help="Print full machine-readable audit")
    args = parser.parse_args()
    data = collect(args.runtime)
    data["target_comparison"] = target_comparison_report(args.runtime)
    print(json.dumps(data, indent=2) if args.json else render(data))
    return 2 if data["missing_databases"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
