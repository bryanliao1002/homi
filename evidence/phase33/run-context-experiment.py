"""Run one paired synthetic context-reduction comparison through the production Mediation Agent."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--database", default="/private/tmp/homi-phase33-context.sqlite")
args = parser.parse_args()
os.environ["HOMI_DATABASE_PATH"] = args.database
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.ai_service import (  # noqa: E402
    AI_MODEL,
    AIServiceError,
    finish_agent_run,
    initialize_usage_logs,
    start_agent_run,
)
from backend.mediation_agents import mediate  # noqa: E402


BASELINE = {
    "perspectives": [
        {
            "participant_id": "riley",
            "perspective": (
                "I work an early shift that starts at 6:30 a.m. and usually leave home a little after six. "
                "Friday I went to bed before 10 because I had an early start. From my bedroom I heard people "
                "talking in the living room at about 10:30 p.m.; I did not go out to check who was still there "
                "or when they left. I would like a heads-up when friends are coming over and for the shared room "
                "to be quiet during quiet hours. I am not asking to ban guests, and I also host friends sometimes. "
                "Earlier that day I made dinner, finished a work call, and moved my laundry; none of that is related."
            ),
        },
        {
            "participant_id": "morgan",
            "perspective": (
                "I invited two friends over Friday. I remember them leaving around 9:45 p.m., before quiet hours, "
                "and I believe the living room was quiet afterward, but I cannot verify exactly what Riley heard "
                "from the bedroom. I want to be able to have friends over occasionally without needing formal "
                "permission every time. I am willing to give notice and follow the quiet-hours rule. I had a busy "
                "week, took the bus home, and was planning a grocery run Saturday; those details are not relevant."
            ),
        },
    ],
    "listening": {
        "neutral_summary": (
            "Riley reports hearing conversation around 10:30 p.m. Friday and wants notice plus quiet during quiet "
            "hours. Morgan recalls two guests leaving around 9:45 p.m. and wants occasional visits to remain "
            "practical. Both accept the quiet-hours rule and neither is asking to prohibit guests."
        ),
        "reported_claims": [
            "Riley reports hearing voices around 10:30 p.m.",
            "Morgan recalls guests leaving around 9:45 p.m.",
        ],
        "shared_information": [
            "Two guests visited Friday.",
            "Both want occasional guests to remain possible.",
        ],
        "unknowns": [
            "The actual departure time and whether conversation continued after 10 p.m. are not independently established."
        ],
        "clarification_questions": [],
    },
    "clarifications": [
        {"participant_id": "riley", "response": "The time is approximate; I did not see the guests leave."},
        {"participant_id": "morgan", "response": "I remember about 9:45 p.m.; nobody else confirmed the time."},
    ],
    "active_rules": [
        {
            "id": "rule-quiet-hours",
            "title": "Quiet hours",
            "detail": "Quiet hours are 10:00 p.m. to 8:00 a.m. Keep shared areas and noise quiet during that period.",
            "category": "Noise",
        },
        {
            "id": "rule-dishes",
            "title": "Shared dishes",
            "detail": "Wash or load personal dishes within 24 hours.",
            "category": "Cleaning",
        },
        {
            "id": "rule-leftovers",
            "title": "Label leftovers",
            "detail": "Label leftovers with the owner and date.",
            "category": "Kitchen",
        },
    ],
}

OPTIMIZED = {
    "perspectives": [
        {
            "participant_id": "riley",
            "perspective": (
                "Riley has a 6:30 a.m. shift and reports hearing guests talking in the living room around 10:30 p.m. "
                "Friday from the bedroom; Riley did not see when they left. Riley wants gathering notice and quiet "
                "during quiet hours, but does not want to ban guests."
            ),
        },
        {
            "participant_id": "morgan",
            "perspective": (
                "Morgan recalls two guests leaving around 9:45 p.m. Friday and believes no voices continued afterward; "
                "the timing is unverified. Morgan wants occasional guests without formal permission each time, is "
                "willing to give notice, and agrees to follow quiet hours."
            ),
        },
    ],
    "listening": {
        "neutral_summary": (
            "Riley reports voices around 10:30 p.m.; Morgan recalls guests leaving around 9:45 p.m. Both accept "
            "quiet hours and want occasional guests to remain possible."
        ),
        "reported_claims": [
            "Riley reports voices around 10:30 p.m.",
            "Morgan recalls guests leaving around 9:45 p.m.",
        ],
        "shared_information": [
            "Two guests visited Friday.",
            "Both want occasional guests to remain possible.",
        ],
        "unknowns": [
            "Departure time and sound after 10 p.m. are not independently confirmed."
        ],
        "clarification_questions": [],
    },
    "clarifications": [
        {"participant_id": "riley", "response": "Time is approximate; Riley did not see guests leave."},
        {"participant_id": "morgan", "response": "Morgan recalls about 9:45 p.m.; no one else confirmed."},
    ],
    "active_rules": [
        {
            "id": "rule-quiet-hours",
            "title": "Quiet hours",
            "detail": "Quiet hours are 10:00 p.m. to 8:00 a.m. Keep shared areas and noise quiet during that period.",
            "category": "Noise",
        }
    ],
}


def main() -> None:
    if AI_MODEL != "gpt-6-luna":
        raise SystemExit("Unexpected model configuration; no request sent.")
    if not os.getenv("PORTKEY_API_KEY", "").strip():
        raise SystemExit("Portkey key is not configured; no request sent.")
    initialize_usage_logs()
    results = []
    suffix = str(time.time_ns())[-10:]
    for variant, case in (("baseline", BASELINE), ("optimized", OPTIMIZED)):
        run_id = f"p33-{variant}-{suffix}"
        start_agent_run(
            run_id=run_id,
            household_id="synthetic-phase33",
            agent_name="mediation",
            agent_version="1.0",
            operation=f"context_reduction_{variant}",
            reasoning_effort="high",
            participant_count=2,
            preference_count=0,
            category_summary=["Noise"],
        )
        try:
            result = mediate(
                run_id=run_id,
                category="Noise",
                perspectives=case["perspectives"],
                listening=case["listening"],
                clarifications=case["clarifications"],
                active_rules=case["active_rules"],
                active_agreements=[],
            )
            finish_agent_run(run_id=run_id, outcome="success", latency_ms=result.result.latency_ms, result=result.result)
            usage = result.result
            results.append(
                {
                    "variant": variant,
                    "requested_model": AI_MODEL,
                    "response_model": usage.model,
                    "reasoning_effort": usage.reasoning_effort,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "reasoning_tokens": usage.reasoning_tokens,
                    "api_latency_ms": usage.latency_ms,
                    "validated_output": result.output,
                }
            )
        except AIServiceError as error:
            finish_agent_run(run_id=run_id, outcome="error", latency_ms=0, error_code=error.code)
            results.append({"variant": variant, "outcome": "error", "error_code": error.code})
    print(json.dumps({"calls": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
