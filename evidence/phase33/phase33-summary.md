# Phase 3.3 — Tokenomics, AI Optimization & Impact

**Measurement date:** 2026-10-26

**Scope:** Read-only source analysis, a scored pair of real synthetic GPT-6 Luna comparison calls (plus an excluded exploratory pair), public-rate estimates, and a prepared pilot questionnaire. No app UI or production prompt changed.

## Tokenomics summary

The sanitized source-of-record export contains **57 SQLite AI-service attempts** across nine development/test databases. There were **40 successful responses, two incomplete output-limit responses, 11 failed HTTP/request responses, and four transport failures with delivery unknown**. Forty-two attempts had token metadata; the remaining 15 have no token counts and are excluded from token-based cost totals. Summed known usage is **23,970 input tokens, 23,067 output tokens, and 13,800 reasoning tokens**. Reasoning tokens are a subset of output tokens. Summed API latency is 257,912 ms across attempts; it is not end-to-end user waiting time.

| Component | Logged attempts | Success / incomplete / failed* | Avg input / output / reasoning tokens† | Avg API latency | Recorded input / output / reasoning tokens |
|---|---:|---:|---:|---:|---:|
| House Rules | 13 | 7 / 1 / 5 | 613.88 / 711.12 / 588.12 | 4,155 ms | 4,911 / 5,689 / 4,705 |
| Listening Agent | 5 | 5 / 0 / 0 | 316.20 / 446.60 / 249.40 | 4,727 ms | 1,581 / 2,233 / 1,247 |
| Mediation Agent | 8 | 7 / 0 / 1 | 760.57 / 746.14 / 351.86 | 5,558 ms | 5,324 / 5,223 / 2,463 |
| Agreement Agent | 4 | 4 / 0 / 0 | 831.75 / 390.25 / 113.00 | 4,709 ms | 3,327 / 1,561 / 452 |
| Smart House Board | 7 | 6 / 1 / 0 | 660.29 / 703.14 / 494.43 | 7,592 ms | 4,622 / 4,922 / 3,461 |
| AI Judge purpose, agent unrecorded | 16 | 9 / 0 / 7 | 463.89 / 380.11 / 163.56 | 3,827 ms | 4,175 / 3,421 / 1,472 |
| Verification | 4 | 2 / 0 / 2 | 15.00 / 9.00 / 0.00 | 644 ms | 30 / 18 / 0 |

\* Failed includes transport errors with delivery unknown. The four such errors are also broken out in `token-usage.csv`.

† Token averages use rows with recorded token data; API latency averages use all logged attempts. Reasoning averages omit null values. Incomplete calls with usage are included. Detailed arithmetic is in `token-usage.csv`.

The backend records the generic purpose `ai_judge` for Listening, Mediation, and Agreement. Where an agent-run record or exact exported Phase 2.3/3.1 evidence identified the agent, it is assigned accordingly. **Sixteen attempts remain unattributed** rather than guessed into those components. This includes nine responses with usage and seven failed requests without usage.

The Phase 2.3, 2.4, 3.1, and 3.2 exported event logs were checked against SQLite token counts and latencies. All **21 exported event records matched existing SQLite rows**; none were added a second time. The exporter skips duplicate provider request IDs and retains older no-ID events as distinct SQLite rows. Source inventory and reconciliation are in `evidence-reconciliation.json`; sanitized row-level data are in `raw-usage.csv`.

## Cost findings

The public OpenAI pricing page lists standard `gpt-6-luna` rates of $0.10 per million input tokens, $0.50 per million output tokens, and $0.01 per million cached input tokens. The exact university Portkey charge is unavailable, so all dollar figures below are **illustrative public-rate estimates, not course billing**. No cached discount is used because the logs do not report cached-input token counts. Reasoning is charged once through `output_tokens`.

| Task | Measured basis | Estimated cost |
|---|---|---:|
| House Rules generation | Mean of five completed `generate_proposals` operations; one operation includes an incomplete response and retry | $0.000609 |
| Smart House Board initial analysis | Mean of three successful `analyze_post` calls; excludes clarification/revision | $0.000344 |
| Full two-roommate mediation | One completed Phase 3.1 workflow: two Listening calls, one Mediation call, one Agreement call | $0.001442 |
| Full mediation cross-check | Component means for the same 2+1+1 call pattern | $0.001394 |

The public-rate estimate for all 42 historical attempts with token metadata is **$0.013931**. It includes incomplete attempts and retries, excludes 15 attempts without token counts, and is not an invoice total.

Monthly scale model: one four-person household has one House Rules generation, four initial Board analyses (one per roommate), and one two-roommate mediation per month. That is about **$0.003428 per household per month** or **$0.000857 per active user per month** when allocated evenly across four residents. Linear estimates are **$0.000857 for 1 user, $0.085712 for 100, and $8.571167 for 10,000 users**. These are usage assumptions, not observed user activity; the one-user number is fractional household expected-value scaling.

Rates, formula, and caveats are documented in `pricing-reference.md`; per-task and scale calculations are in `cost-model.csv` and reproducible from the sanitized raw CSV.

## Context-reduction experiment

The final scored pair used the production `mediation_agents.mediate` function on the same fictional Friday guest/noise disagreement. Both used `gpt-6-luna`, high reasoning effort, a 2,200-token output budget, the same role instructions and schema, and the same relevant approved quiet-hours rule. The baseline included full synthetic statements, listening summary, and three active rules. The optimized version preserved the early-shift, notice-willingness, disputed-time, and other material facts while shortening equivalent text and dropping two unrelated rules. Four real provider responses were recorded for this experiment: an initial exploratory pair and this final pair. The exploratory compact input omitted Morgan's willingness to give notice and Riley's early-shift detail, so it was excluded from the comparison but retained in the raw usage ledger and historical totals.

| Variant | Input | Output | Reasoning subset | API latency | Estimated call cost | Qualitative score / 5 |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 864 | 528 | 142 | 557 ms | $0.0003504 | 4.6 |
| Optimized context | 656 | 528 | 186 | 4,652 ms | $0.0003296 | 4.8 |

Observed final-pair changes: input tokens −24.1%, output tokens unchanged, reasoning tokens +31.0%, API latency was 4.652 seconds optimized versus 0.557 seconds baseline, and illustrative cost −5.9% (about **$0.0000208 saved per Mediation call**). Both outputs attributed the conflicting times, retained uncertainty, cited only the supplied quiet-hours rule, avoided a breach/guilt finding, and proposed a practical voluntary next step. The large latency spread and reasoning-token change across just two requests show why the result should be treated as a small sample, not a performance guarantee.

Quality ratings were one qualitative review by this assistant, not an independent human or a separate model-judge call. Automated checks confirmed valid structured output, attributed claims, nonempty uncertainties, the supplied rule ID, no guilt finding, and a nonempty resolution. This is one paired scenario with no statistical significance. The result suggests a possible context-reduction saving but is not sufficient to change production prompts; those remain untouched.

The final paired call record, excluded exploratory-pair note, and validated synthetic outputs are in `evaluation-results.json` and `optimization-results.csv`. The reproducible runner is `run-context-experiment.py`; all four response usage rows and the tokenless network failure are in `raw-usage.csv`.

## Impact summary

- **Simulated:** both variants in the final scored pair returned a validated proposal for one fictional disagreement; an earlier exploratory pair is retained but excluded from scoring.
- **Recorded workflow completion:** Phase 3.1 browser evidence documents one test mediation reaching agreement activation after two required roommate approvals. This shows the workflow completed in that scenario, not that AI caused a real resolution.
- **Generation time:** that workflow used 26,593 ms of summed API latency across its four agents. Full elapsed user time, including roommate response/approval time, was not recorded.
- **Output-quality proxy:** the one-scenario rubric is in `optimization-results.csv`. These ratings are not participant perceptions.
- **Actual human feedback:** none collected. Perceived fairness, willingness to use homi. again, and real-world conflict outcomes remain pending a pilot.

The 7-question 1–5 pilot questionnaire plus one optional open-ended question is ready at `pilot-questionnaire.md`. No real-user responses are included or invented.

## Key limitations and recommendations

- Portkey course billing may differ from public direct API rates; no billing export was available.
- Some historical `ai_judge` records lack agent-run metadata and remain unattributed.
- Fifteen log attempts lack usage counts; their costs cannot be calculated. Four transport failures have unknown delivery state.
- The optimization experiment scored one final pair within four real model responses total, using one scenario and a non-independent qualitative reviewer. Do not generalize or claim statistical significance.
- Human impact is unmeasured. Do not claim conflict reduction until a consented pilot measures it.
- Demo profile switching is not authentication; the questionnaire should avoid collecting sensitive statements.

Suggested final visuals:

1. Stacked component chart of successful, incomplete, and failed calls, next to average input/output tokens and estimated public-rate cost.
2. Four-agent mediation flow table showing call count, recorded tokens, API latency, and observed illustrative cost for the Phase 3.1 scenario.
3. Paired baseline/optimized chart for input tokens, cost, latency, and the five rubric scores, with `n=1` scenario clearly shown.

## Claim sources

| Claim | Source files |
|---|---|
| Historical raw counts and component averages | `raw-usage.csv`, `token-usage.csv`, `export_usage.py`, and `evidence-reconciliation.json`; original SQLite snapshots are local working data and are intentionally excluded from the public repository |
| API log fields, model/purpose labels, and usage-token semantics captured by the backend | `backend/ai_service.py` |
| Component operations used for per-task rates | `backend/house_rules_agent.py`, `backend/house_board_agent.py`, `backend/mediation_agents.py` |
| Historical agent mapping | `evidence/phase23-agent-evidence.json`, `evidence/phase31-integration.json`, `evidence/phase32-safety/live-ai-usage.json` |
| Board retry/incomplete record | `evidence/phase24-workflow.json`, `backend/house_board_agent.py` |
| Public price and billing caveat | `pricing-reference.md`, `https://developers.openai.com/api/docs/pricing` |
| Reasoning tokens charged as output | `https://developers.openai.com/api/docs/guides/reasoning`; `evidence/phase24-workflow.json` |
| Context experiment and quality assessment | `run-context-experiment.py`, `optimization-results.csv`, `evaluation-results.json`, `backend/mediation_agents.py` |
| Completed browser mediation and approvals | `evidence/phase31-integration.json` |
| Pilot questions and pending human data | `pilot-questionnaire.md`, `evaluation-results.json` |

## Reproduction

The committed `raw-usage.csv` and `evidence-reconciliation.json` are the sanitized evidence of record. Original SQLite snapshots are intentionally excluded because they contain local household data. If you have authorized local snapshots, set `HOMI_USAGE_DATABASES` to their paths (a path-separated list), then run:

```bash
.venv/bin/python evidence/phase33/export_usage.py
.venv/bin/python evidence/phase33/summarize_phase33.py
.venv/bin/python evidence/phase33/verify_phase33.py
```

The exporter uses only Python's standard library and selects usage metadata, not prompts, responses, API keys, household identifiers, or request IDs. With no `HOMI_USAGE_DATABASES` value it checks only the project's ignored `backend/data/homi.sqlite`. `verify_phase33.py` checks the committed token totals, cost arithmetic, export matches, and deterministic output assertions. To rerun the live paired experiment, see `run-context-experiment.py`; it sends two synthetic requests through the university Portkey key and incurs actual usage.
