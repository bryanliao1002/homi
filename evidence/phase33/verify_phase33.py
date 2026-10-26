"""Check Phase 3.3 evidence arithmetic and deterministic experiment assertions."""
from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path


HERE = Path(__file__).resolve().parent
raw = list(csv.DictReader((HERE / "raw-usage.csv").open(newline="", encoding="utf-8")))
usage = list(csv.DictReader((HERE / "token-usage.csv").open(newline="", encoding="utf-8")))
costs = {r["metric"]: r for r in csv.DictReader((HERE / "cost-model.csv").open(newline="", encoding="utf-8"))}
optimization_csv = {r["variant"]: r for r in csv.DictReader((HERE / "optimization-results.csv").open(newline="", encoding="utf-8"))}
reconciliation = json.loads((HERE / "evidence-reconciliation.json").read_text())
evaluation = json.loads((HERE / "evaluation-results.json").read_text())

assert len(raw) == 57, f"Unexpected SQLite event row count: {len(raw)}"
assert sum(int(r["logged_attempts"]) for r in usage) == len(raw)
totals = {
    field: sum(int(r[field]) for r in raw if r[field] != "")
    for field in ("input_tokens", "output_tokens", "reasoning_tokens", "api_latency_ms")
}
assert totals == {
    "input_tokens": 23970,
    "output_tokens": 23067,
    "reasoning_tokens": 13800,
    "api_latency_ms": 257912,
}
assert sum(int(r["successful_calls"]) for r in usage) == 40
assert sum(int(r["incomplete_output_calls"]) for r in usage) == 2
assert sum(int(r["failed_calls"]) for r in usage) == 15
assert sum(x["matched_to_sqlite_rows"] for x in reconciliation["exported_evidence_checks"]) == 21
assert reconciliation["exported_evidence_rows_added_again"] == 0

checks = evaluation["optimization_experiment"]["quality_review"]["automated_checks"]
variants = evaluation["optimization_experiment"]["results"]
assert len(variants) == 2
relevant_rule = "rule-quiet-hours"
for variant in variants:
    raw_variant = max(
        (r for r in raw if r["source_db"] == "homi-phase33-context-live.sqlite" and r["agent_operation"] == f"context_reduction_{variant['variant']}"),
        key=lambda r: int(r["source_row_id"]),
    )
    for field in ("input_tokens", "output_tokens", "reasoning_tokens", "api_latency_ms"):
        assert int(raw_variant[field]) == int(variant["reasoning_tokens_subset"] if field == "reasoning_tokens" else variant[field])
for variant in variants:
    output = variant["validated_output"]
    assert output["reported_claims"] and output["uncertainties"]
    assert output["proposed_resolution"].strip()
    assert {r["rule_id"] for r in output["rule_analysis"]} == {relevant_rule}
    assert any("riley" in c.lower() for c in output["reported_claims"])
    assert any("morgan" in c.lower() for c in output["reported_claims"])
    assert any(any(s in u.lower() for s in ("unknown", "unverified", "not independently")) for u in output["uncertainties"])
    rule_text = " ".join(r["relationship"].lower() for r in output["rule_analysis"])
    assert "not establish" in rule_text or "do not establish" in rule_text
    resolution = output["proposed_resolution"].lower()
    assert not any(f"{name} {verb}" in resolution for name in ("riley", "morgan") for verb in ("violated", "breached", "is guilty", "is at fault"))
assert all(checks.values())

price_input = Decimal("0.10")
price_output = Decimal("0.50")
for variant in variants:
    expected = (
        Decimal(variant["input_tokens"]) * price_input
        + Decimal(variant["output_tokens"]) * price_output
    ) / Decimal(1_000_000)
    assert abs(expected - Decimal(str(variant["illustrative_cost_usd"]))) < Decimal("0.0000000001")
    csv_variant = optimization_csv[variant["variant"]]
    assert int(csv_variant["input_tokens"]) == variant["input_tokens"]
    assert int(csv_variant["output_tokens"]) == variant["output_tokens"]
    assert int(csv_variant["reasoning_tokens_subset"]) == variant["reasoning_tokens_subset"]
    assert int(csv_variant["api_latency_ms"]) == variant["api_latency_ms"]

historical_cost = (
    Decimal(totals["input_tokens"]) * Decimal("0.10")
    + Decimal(totals["output_tokens"]) * Decimal("0.50")
) / Decimal(1_000_000)
assert abs(historical_cost - Decimal(costs["All logged calls with token usage"]["estimated_usd"])) < Decimal("0.000000001")

assert evaluation["optimization_experiment"]["production_prompt_changed"] is False
assert evaluation["optimization_experiment"]["real_provider_calls"] == 4
assert evaluation["optimization_experiment"]["final_scored_pair_calls"] == 2
assert evaluation["impact_measurement"]["actual_human_feedback"]["participants"] == 0
print("Phase 3.3 evidence checks passed: 57 rows, 21 export matches, token totals, final paired outputs, and public-rate arithmetic.")
