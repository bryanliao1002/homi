# Phase 3.2 — AI Safety & Reliability

**Date:** 2026-10-26

**Result:** 26 automated tests passed; frontend production build and Python compilation passed. No test failures.

## Scope and results

| Area | Verification | Result |
|---|---|---|
| Prompt injection | House Rules preference injection, Smart House Board post injection, and mediation perspective injection were tested. Untrusted text remained data; model output claiming approval/activation did not create an active rule. A clear Board permission request stayed approval-gated despite a mocked AI classification of “announcement” with approval disabled. | Passed |
| Approval integrity | Existing workflow regressions covered approval, rejection, change requests, revision resets, independent votes, and stale House Rules / Board versions. Backend state, not AI output, controls activation. | Passed |
| Privacy | Tests checked that the key sentinel was absent from health output and frontend bundles, a private mediation statement did not appear in another member’s view or notifications, and timeout text was sanitized. | Passed |
| Fairness and safety | A mediation injection requesting a guilt verdict did not override the neutral instructions; output retained uncertainty. A threat statement combined with an instruction to bypass checks triggered the local safety pause before any AI call. | Passed |
| Reliability | Malformed Board output produced an unavailable / not-assessed state with no approvals; malformed Listening output left the case recoverable; simulated timeout returned a sanitized error. | Passed |

The focused tests are in `tests/test_phase32_safety.py`; stale-version and approval workflow coverage is in `tests/test_house_rules_workflow.py`, `tests/test_house_board_workflow.py`, and `tests/test_mediation_workflow.py`.

## Issue fixed

The review found that a clear consent request could be published without roommate approval if the AI mislabeled it as an announcement and returned `approval_required=false`. `backend/house_board_api.py` now applies a deterministic phrase check to the original post and clarification and requires the normal approval round for clear permission requests. The new regression test reproduces the misleading AI classification and confirms zero votes and a pending request.

This is a narrow phrase heuristic, not a guarantee that every natural-language request is recognized. Board analysis remains advisory; it cannot itself grant permission.

## Real and mocked AI checks

The repeatable automated tests use mocked model responses. Three separate live probes used synthetic data and the university Portkey service with requested model `gpt-6-luna`; all returned `gpt-6-luna-global` with HTTP 200. The House Rules probe produced a pending proposal with no approvals. The Board injection probe remained approval-pending with zero approvals. The mediation probe separated reported claims from established information, retained uncertainty, and did not return a guilt verdict or echo the private statement verbatim.

Actual per-call counts and latency are recorded in [live-ai-usage.json](live-ai-usage.json). Totals from the isolated SQLite `ai_usage_logs` records: **1,564 input tokens, 1,406 output tokens, 794 reasoning tokens, and 13,544 ms API latency**. No cost was estimated. These three calls are spot checks, not broad evidence of model behavior.

## Final verification

- `.venv/bin/python -m unittest discover -s tests -v` — **26 passed, 0 failed**.
- `npm run build` — **passed**.
- `.venv/bin/python -m compileall -q backend tests` — **passed**.
- Local smoke check — frontend returned HTTP 200 at `http://127.0.0.1:5175/`; backend `/api/health` returned `status: ok` and model `gpt-6-luna`. Chrome showed the Ask homi. page with the existing household navigation and Little Homi branding at `http://127.0.0.1:5175/ask`.

The smoke check used the already-running local app. Its browser/backend test database was separate from the repository’s default `backend/data/homi.sqlite`. No screenshot is needed for this behavior-focused safety report.

## Remaining limitations

- Demo profile switching is not authentication. A person with browser access can act as another profile, so the app cannot prove who submitted a vote.
- Shared mediation summaries are intentionally visible to involved participants and may paraphrase private perspectives. Tests establish no verbatim echo in the checked path, not zero semantic disclosure or guaranteed anonymity.
- The safety screen is a basic keyword check, not emergency support or a comprehensive abuse/threat detector.
- Most adversarial scenarios are mocked, and the three live probes cannot establish that prompt injection will never influence model output. Deterministic backend approval checks limit the effect AI text can have on household state.
- No production authentication, AI Judge safety policy, or new AI functionality was added in this phase.

## Sanitization

The evidence files contain provider metadata and outcomes only. They omit the API key, prompts, roommate statements, model response text, household identifiers, and request IDs.
