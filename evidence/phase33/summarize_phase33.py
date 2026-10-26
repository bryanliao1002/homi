"""Recompute usage summaries and illustrative cost estimates from the sanitized raw CSV."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path


HERE = Path(__file__).resolve().parent
INPUT_RATE = Decimal("0.10")  # USD per 1M standard input tokens, public reference only
OUTPUT_RATE = Decimal("0.50")  # USD per 1M standard output tokens, reasoning included
MILLION = Decimal(1_000_000)
COMPONENT_ORDER = [
    "House Rules", "Listening", "Mediation", "Agreement", "Smart House Board",
    "AI Judge (unattributed)", "Verification",
]


def load_raw() -> list[dict[str, str]]:
    with (HERE / "raw-usage.csv").open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def number(row: dict[str, str], key: str) -> int | None:
    return int(row[key]) if row.get(key, "") != "" else None


def mean(values: list[int]) -> str:
    return f"{sum(values) / len(values):.2f}" if values else ""


def write_token_summary(rows: list[dict[str, str]]) -> None:
    fields = [
        "component", "logged_attempts", "successful_calls", "incomplete_output_calls",
        "failed_calls", "transport_failure_delivery_unknown", "calls_with_token_data",
        "avg_input_tokens_when_recorded", "avg_output_tokens_when_recorded",
        "avg_reasoning_tokens_when_recorded", "avg_api_latency_ms_all_attempts",
        "total_input_tokens_recorded", "total_output_tokens_recorded",
        "total_reasoning_tokens_recorded_subset", "total_api_latency_ms",
    ]
    out = []
    for component in COMPONENT_ORDER:
        group = [r for r in rows if r["component"] == component]
        if not group:
            continue
        classes = Counter(r["result_class"] for r in group)
        inputs = [v for r in group if (v := number(r, "input_tokens")) is not None]
        outputs = [v for r in group if (v := number(r, "output_tokens")) is not None]
        reasoning = [v for r in group if (v := number(r, "reasoning_tokens")) is not None]
        latencies = [int(r["api_latency_ms"]) for r in group]
        out.append({
            "component": component,
            "logged_attempts": len(group),
            "successful_calls": classes["success"],
            "incomplete_output_calls": classes["incomplete_output_limit"],
            "failed_calls": classes["failed"] + classes["transport_failure_delivery_unknown"],
            "transport_failure_delivery_unknown": classes["transport_failure_delivery_unknown"],
            "calls_with_token_data": len(inputs),
            "avg_input_tokens_when_recorded": mean(inputs),
            "avg_output_tokens_when_recorded": mean(outputs),
            "avg_reasoning_tokens_when_recorded": mean(reasoning),
            "avg_api_latency_ms_all_attempts": mean(latencies),
            "total_input_tokens_recorded": sum(inputs),
            "total_output_tokens_recorded": sum(outputs),
            "total_reasoning_tokens_recorded_subset": sum(reasoning),
            "total_api_latency_ms": sum(latencies),
        })
    with (HERE / "token-usage.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)


def cost_usd(input_tokens: Decimal | int | float, output_tokens: Decimal | int | float) -> Decimal:
    return (Decimal(str(input_tokens)) * INPUT_RATE + Decimal(str(output_tokens)) * OUTPUT_RATE) / MILLION


def aggregate_task_groups(group: list[dict[str, str]]) -> dict[str, int]:
    return {
        "input": sum(number(r, "input_tokens") or 0 for r in group),
        "output": sum(number(r, "output_tokens") or 0 for r in group),
        "reasoning": sum(number(r, "reasoning_tokens") or 0 for r in group),
        "latency": sum(int(r["api_latency_ms"]) for r in group),
        "attempts": len(group),
    }


def unit_task_groups(rows: list[dict[str, str]], component: str, operation: str, *, successful_only=True):
    groups: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if row["component"] != component or row["agent_operation"] != operation or not row["agent_run_key"]:
            continue
        groups[(row["source_db"], row["agent_run_key"])].append(row)
    result = []
    for group in groups.values():
        if successful_only and not any(row["result_class"] == "success" for row in group):
            continue
        result.append(aggregate_task_groups(group))
    return result


def write_cost_model(rows: list[dict[str, str]]) -> None:
    cost_rows = []

    def add(metric, basis, task_count, attempts, in_tokens, out_tokens, reasoning, cost, assumption):
        cost_rows.append({
            "metric": metric,
            "basis": basis,
            "n_tasks_or_scenarios": task_count,
            "provider_attempts": attempts,
            "input_tokens_per_task_or_total": f"{Decimal(str(in_tokens)):.2f}" if in_tokens is not None else "",
            "output_tokens_per_task_or_total": f"{Decimal(str(out_tokens)):.2f}" if out_tokens is not None else "",
            "reasoning_tokens_subset_per_task_or_total": f"{Decimal(str(reasoning)):.2f}" if reasoning is not None else "",
            "estimated_usd": f"{cost:.9f}" if cost is not None else "",
            "assumption": assumption,
        })

    hr = unit_task_groups(rows, "House Rules", "generate_proposals")
    hr_i = sum(x["input"] for x in hr) / len(hr)
    hr_o = sum(x["output"] for x in hr) / len(hr)
    hr_r = sum(x["reasoning"] for x in hr) / len(hr)
    add("House Rules proposal generation", "Mean completed generate_proposals operation", len(hr), sum(x["attempts"] for x in hr), hr_i, hr_o, hr_r, cost_usd(hr_i, hr_o), "Five completed operations; one includes an output-limit attempt and its retry, both priced.")

    board = unit_task_groups(rows, "Smart House Board", "analyze_post")
    board_i = sum(x["input"] for x in board) / len(board)
    board_o = sum(x["output"] for x in board) / len(board)
    board_r = sum(x["reasoning"] for x in board) / len(board)
    add("Smart House Board initial analysis", "Mean successful analyze_post operation", len(board), sum(x["attempts"] for x in board), board_i, board_o, board_r, cost_usd(board_i, board_o), "Three complete initial analyses; excludes later clarification/revision steps.")

    historical_means = {}
    for component in ("Listening", "Mediation", "Agreement"):
        selected = [
            r for r in rows
            if r["component"] == component and r["result_class"] == "success"
            and not r["source_db"].startswith("homi-phase33-")
            and number(r, "input_tokens") is not None and number(r, "output_tokens") is not None
        ]
        in_avg = sum(number(r, "input_tokens") for r in selected) / len(selected)
        out_avg = sum(number(r, "output_tokens") for r in selected) / len(selected)
        reason_vals = [number(r, "reasoning_tokens") for r in selected if number(r, "reasoning_tokens") is not None]
        reason_avg = sum(reason_vals) / len(reason_vals) if reason_vals else None
        historical_means[component] = (in_avg, out_avg, reason_avg, len(selected))
        add(f"{component} Agent call", "Mean attributed successful historical calls", len(selected), len(selected), in_avg, out_avg, reason_avg, cost_usd(in_avg, out_avg), "Per-call estimate from component-attributed successful logs; Phase 3.3 optimization probes excluded.")

    phase31_case = [
        r for r in rows
        if r["source_db"] == "homi-phase31-integration.sqlite"
        and r["component"] in ("Listening", "Mediation", "Agreement")
        and r["result_class"] == "success"
    ]
    full = aggregate_task_groups(phase31_case)
    add("Full two-roommate mediation", "One observed Phase 3.1 completed case", 1, full["attempts"], full["input"], full["output"], full["reasoning"], cost_usd(full["input"], full["output"]), "Two Listening calls + one Mediation call + one Agreement call; API latency sum is not wall-clock workflow time.")

    li, lo, lr, ln = historical_means["Listening"]
    mi, mo, mr, mn = historical_means["Mediation"]
    ai, ao, ar, an = historical_means["Agreement"]
    modeled_i, modeled_o = 2 * li + mi + ai, 2 * lo + mo + ao
    modeled_r = 2 * lr + mr + ar if None not in (lr, mr, ar) else None
    add("Full mediation from component means", "Modeled two-participant workflow", 1, 4, modeled_i, modeled_o, modeled_r, cost_usd(modeled_i, modeled_o), "Two mean Listening calls + one mean Mediation call + one mean Agreement call.")

    experiment = [
        r for r in rows
        if r["source_db"] == "homi-phase33-context-live.sqlite"
        and r["agent_operation"] in ("context_reduction_baseline", "context_reduction_optimized")
        and r["result_class"] == "success"
    ]
    for variant in ("baseline", "optimized"):
        selected = max(
            (r for r in experiment if r["agent_operation"] == f"context_reduction_{variant}"),
            key=lambda r: int(r["source_row_id"]),
        )
        i, o, reasoning = (int(selected[k]) for k in ("input_tokens", "output_tokens", "reasoning_tokens"))
        add(f"Context experiment {variant}", "One real gpt-6-luna call", 1, 1, i, o, reasoning, cost_usd(i, o), "Fictional scenario; identical agent instructions, effort, schema, and output budget.")

    known = [r for r in rows if number(r, "input_tokens") is not None and number(r, "output_tokens") is not None]
    all_i = sum(number(r, "input_tokens") for r in known)
    all_o = sum(number(r, "output_tokens") for r in known)
    all_r = sum(number(r, "reasoning_tokens") or 0 for r in known)
    add("All logged calls with token usage", "Historical observed records, illustrative only", len(known), len(known), all_i, all_o, all_r, cost_usd(all_i, all_o), f"{len(known)} usage-bearing attempts; excludes {len(rows) - len(known)} attempts with no token counts. Output tokens already include reasoning; no cache discount applied.")

    household_cost = cost_usd(hr_i, hr_o) + 4 * cost_usd(board_i, board_o) + cost_usd(full["input"], full["output"])
    per_user = household_cost / Decimal(4)
    add("Monthly cost per active user", "Linear four-person household scenario", 1, None, None, None, None, per_user, "Per household/month: 1 Rules generation + 4 Board analyses + 1 two-person mediation; divided by 4 residents.")
    for users in (1, 100, 10000):
        add(f"Monthly projection for {users} active user(s)", "Linear scaling from stated household scenario", users, None, None, None, None, per_user * users, "Assumes all users are active and households average four; fractional households are expected-value scaling.")

    fields = list(cost_rows[0])
    with (HERE / "cost-model.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(cost_rows)


def main() -> None:
    rows = load_raw()
    write_token_summary(rows)
    write_cost_model(rows)
    print(f"Recomputed token-usage.csv and cost-model.csv from {len(rows)} sanitized raw rows.")


if __name__ == "__main__":
    main()
