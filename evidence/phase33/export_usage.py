"""Export sanitized API usage metadata from Phase 1–3.3 SQLite snapshots.

Only ai_usage_logs and safe agent-run metadata are read. Roommate statements,
prompts, model response text, API keys, household IDs, and request IDs are not
selected or written. Exported JSON evidence is reconciled but never added again.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sqlite3
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence"
OUT = EVIDENCE / "phase33"


def _source_databases() -> list[Path]:
    configured = os.environ.get("HOMI_USAGE_DATABASES", "")
    if configured.strip():
        return [Path(item).expanduser() for item in configured.split(os.pathsep) if item.strip()]
    return [ROOT / "backend" / "data" / "homi.sqlite"]


def _evidence_agent_map() -> dict[tuple[int | None, ...], str]:
    mapping: dict[tuple[int | None, ...], str] = {}

    def add(component: str, usage: dict, latency_key: str) -> None:
        key = (
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            usage.get("reasoning_tokens"),
            usage.get(latency_key),
        )
        if all(isinstance(value, int) for value in key):
            mapping[key] = component

    phase23 = json.loads((EVIDENCE / "phase23-agent-evidence.json").read_text())
    for run in phase23.get("agent_runs", []):
        add(run.get("agent", "AI Judge (unattributed)"), run.get("usage", {}), "api_latency_ms")

    phase31 = json.loads((EVIDENCE / "phase31-integration.json").read_text())
    for call in phase31.get("live_ai_verification", {}).get("calls", []):
        add(call.get("agent", "AI Judge (unattributed)"), call, "latency_ms")

    # Phase 3.2's synthetic live mediation probe used the ai_judge API purpose,
    # and the report identifies this one 492/787-token record as the Mediation Agent.
    mapping[(492, 787, 445, 6326)] = "mediation"
    return mapping


def _result_class(outcome: str, status: int | None, error_code: str | None) -> str:
    if outcome == "success":
        return "success"
    if status == 200 and error_code == "output_limit_reached":
        return "incomplete_output_limit"
    if error_code == "network_error":
        return "transport_failure_delivery_unknown"
    return "failed"


def _component(purpose: str, agent: str | None, op: str | None, usage: tuple, map_by_usage: dict) -> tuple[str, str]:
    if purpose == "house_rules":
        return "House Rules", "SQLite purpose"
    if purpose == "smart_board":
        return "Smart House Board", "SQLite purpose"
    if purpose == "verification":
        return "Verification", "SQLite purpose"
    if purpose == "ai_judge":
        if agent in {"listening", "mediation", "agreement"}:
            return agent.title(), "SQLite agent run"
        if usage in map_by_usage:
            return map_by_usage[usage].title(), "matched exported agent evidence"
        return "AI Judge (unattributed)", "agent name unavailable"
    return "Other", "unmapped purpose"


def collect() -> tuple[list[dict], dict]:
    evidence_map = _evidence_agent_map()
    rows: list[dict] = []
    seen_request_ids: set[str] = set()
    duplicate_request_rows = 0
    databases_read = []

    for path in _source_databases():
        if not path.is_file():
            continue
        uri = path.resolve().as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=3)
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "ai_usage_logs" not in tables:
            db.close()
            continue
        columns = {r[1] for r in db.execute("PRAGMA table_info(ai_usage_logs)")}
        selected = [
            "id", "created_at", "purpose", "model", "reasoning_effort", "input_tokens",
            "output_tokens", "reasoning_tokens", "latency_ms", "outcome", "http_status", "error_code",
        ]
        selected += [name for name in ("agent_run_id", "request_id") if name in columns]
        source_count = 0
        for source_row in db.execute(f"SELECT {','.join(selected)} FROM ai_usage_logs ORDER BY id"):
            d = dict(source_row)
            request_id = d.get("request_id")
            if request_id and request_id in seen_request_ids:
                duplicate_request_rows += 1
                continue
            if request_id:
                seen_request_ids.add(request_id)

            agent = operation = None
            run_id = d.get("agent_run_id")
            if run_id and "ai_agent_runs" in tables:
                run = db.execute(
                    "SELECT agent_name, operation FROM ai_agent_runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if run:
                    agent, operation = run[0], run[1]

            key = (d.get("input_tokens"), d.get("output_tokens"), d.get("reasoning_tokens"), d.get("latency_ms"))
            component, attribution = _component(d["purpose"], agent, operation, key, evidence_map)
            error = d.get("error_code")
            row = {
                "source_db": path.name,
                "source_row_id": d["id"],
                "created_at_utc": d["created_at"],
                "component": component,
                "attribution_basis": attribution,
                "purpose": d["purpose"],
                "agent_operation": operation or "",
                "agent_run_key": hashlib.sha256(run_id.encode()).hexdigest()[:12] if run_id else "",
                "model_label": d["model"],
                "reasoning_effort": d["reasoning_effort"],
                "result_class": _result_class(d["outcome"], d.get("http_status"), error),
                "http_status": d.get("http_status") if d.get("http_status") is not None else "",
                "error_code": error or "",
                "input_tokens": d.get("input_tokens") if d.get("input_tokens") is not None else "",
                "output_tokens": d.get("output_tokens") if d.get("output_tokens") is not None else "",
                "reasoning_tokens": d.get("reasoning_tokens") if d.get("reasoning_tokens") is not None else "",
                "api_latency_ms": d["latency_ms"],
                "request_id_present": bool(request_id),
            }
            rows.append(row)
            source_count += 1
        databases_read.append({"source_db": path.name, "deduplicated_rows": source_count})
        db.close()

    rows.sort(key=lambda x: (x["source_db"], int(x["source_row_id"])))
    event_keys = Counter(
        (
            int(r["input_tokens"]) if r["input_tokens"] != "" else None,
            int(r["output_tokens"]) if r["output_tokens"] != "" else None,
            int(r["reasoning_tokens"]) if r["reasoning_tokens"] != "" else None,
            int(r["api_latency_ms"]),
        )
        for r in rows
    )

    checks = []

    def reconcile(label: str, events: list[tuple]) -> None:
        available = event_keys.copy()
        matched = 0
        for event in events:
            if available[event] > 0:
                available[event] -= 1
                matched += 1
        checks.append({
            "evidence_file": label,
            "exported_event_records": len(events),
            "matched_to_sqlite_rows": matched,
            "additional_rows_added_to_analysis": 0,
        })

    p23 = json.loads((EVIDENCE / "phase23-agent-evidence.json").read_text())
    reconcile(
        "evidence/phase23-agent-evidence.json",
        [
            (u.get("input_tokens"), u.get("output_tokens"), u.get("reasoning_tokens"), u.get("api_latency_ms"))
            for a in p23.get("agent_runs", []) for u in [a.get("usage", {})]
        ],
    )
    p24 = json.loads((EVIDENCE / "phase24-workflow.json").read_text())
    reconcile(
        "evidence/phase24-workflow.json",
        [
            (c.get("input_tokens"), c.get("output_tokens"), c.get("reasoning_tokens"), c.get("api_latency_ms"))
            for c in p24.get("live_ai_usage", {}).get("calls", [])
        ],
    )
    p31 = json.loads((EVIDENCE / "phase31-integration.json").read_text())
    reconcile(
        "evidence/phase31-integration.json",
        [
            (c.get("input_tokens"), c.get("output_tokens"), c.get("reasoning_tokens"), c.get("latency_ms"))
            for c in p31.get("live_ai_verification", {}).get("calls", [])
        ],
    )
    p32 = json.loads((EVIDENCE / "phase32-safety" / "live-ai-usage.json").read_text())
    reconcile(
        "evidence/phase32-safety/live-ai-usage.json",
        [
            (c.get("input_tokens"), c.get("output_tokens"), c.get("reasoning_tokens"), c.get("api_latency_ms"))
            for c in p32.get("calls", [])
        ],
    )

    reconciliation = {
        "sqlite_rows_included": len(rows),
        "duplicate_request_id_rows_skipped": duplicate_request_rows,
        "unique_request_ids_seen": len(seen_request_ids),
        "database_sources": databases_read,
        "exported_evidence_checks": checks,
        "exported_evidence_rows_added_again": 0,
        "method": "SQLite request rows are the event source of record; JSON event rows are exact-matched by tokens and latency as cross-checks only.",
        "caveat": "Older rows without provider request IDs are retained as distinct SQLite row IDs; no evidence export rows are appended."
    }
    return rows, reconciliation


def write_outputs(rows: list[dict], reconciliation: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw_path = OUT / "raw-usage.csv"
    fields = list(rows[0]) if rows else []
    with raw_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "evidence-reconciliation.json").write_text(json.dumps(reconciliation, indent=2) + "\n")


if __name__ == "__main__":
    exported, details = collect()
    write_outputs(exported, details)
    print(json.dumps(details, indent=2))
