# homi. Evidence Index

This index points to preserved evidence for the final project. “Measured” means directly observed in a test run or provider usage record. “Simulated” means fictional test input or a mocked response. “Estimate” means a calculation from an assumption or public price, not a Portkey invoice. No pilot feedback is included unless future participants complete the questionnaire.

## Verification and product evidence

| Evidence | Type | What it supports | Limits |
|---|---|---|---|
| `phase23-agent-evidence.json` | Measured API metadata + fictional workflow | Phase 2.3 mediation-agent execution, actual token/latency records and workflow outcomes | Synthetic case; a single run does not establish fairness or effectiveness |
| `phase24-workflow.json` | Measured API metadata + fictional workflow | Smart House Board analysis, approval flow, and actual usage fields | Synthetic household text; not a broad model evaluation |
| `phase31-integration.json` | Measured automated/browser verification + real API metadata | Cross-feature integration, demo household workflow, seven live AI calls, and historical 18-test result | Earlier Phase 3.1 build; use `phase34-verification.json` for current source verification |
| `phase32-safety/REPORT.md` | Mocked tests + three measured live probes | Prompt-injection, approval, privacy, safety, and reliability tests; issue found and fixed | Live probes are synthetic spot checks, not a guarantee against all unsafe behavior |
| `phase32-safety/live-ai-usage.json` | Measured provider metadata | Actual model labels, usage counts, effort, and latency for the three safety probes | Does not include prompt or response text |
| `phase33/phase33-summary.md` | Measured logs + simulated evaluation + estimates | Historical usage reconciliation, a one-scenario optimization comparison, public-rate estimates, and impact-measurement limitations | Public-rate dollars are estimates, not university Portkey billing; no human pilot results |
| `phase33/raw-usage.csv`, `phase33/token-usage.csv`, `phase33/evidence-reconciliation.json` | Sanitized measured metadata | Source rows and reproducible historical counts | 15 historical attempts lacked token metadata; four delivery outcomes are unknown |
| `phase33/cost-model.csv`, `phase33/pricing-reference.md` | Estimates | Illustrative cost arithmetic using published rates | Not a bill; cached-token discounts are not assumed |
| `phase33/optimization-results.csv`, `phase33/evaluation-results.json` | Simulated scenario + measured API responses | One scored, fictional context-reduction comparison and rubric | One scenario, qualitative review, no statistical inference |
| `phase33/pilot-questionnaire.md` | Prepared research instrument | Questions for an optional, consented user pilot | No responses or impact findings are claimed |
| `phase34-verification.json` | Measured local verification | Current Phase 3.4 test/build/syntax, data-isolation, and fresh-clone results | AI usage is reported only if a real provider call is recorded; test fixtures are never presented as provider usage |

## Product screenshots

The curated screenshots in [`final-screenshots/public/`](final-screenshots/public/) show the current welcome page, dashboard, House Rules, House Board, Ask homi., chores, and bills screens. They use seeded demo profiles and household data. The raw uploads, duplicate `Screenshots/` folder, and AI Judge captures with detailed roommate case text are excluded from the public repository. The three filled survey PDFs are also excluded because their response provenance has not been verified. No human-pilot findings are claimed.

Earlier Phase 1 and redesign screenshots were removed from the publication set because they are superseded by the current captures. The Phase 3.4 verification record remains in `phase34-verification.json`; it describes the earlier automated-capture limitation accurately. Additional safe capture guidance is in [`final-screenshots/MANUAL-CAPTURE.md`](final-screenshots/MANUAL-CAPTURE.md).

## Reproduction

From the project root:

```bash
HOMI_DATABASE_PATH=/private/tmp/homi-tests.sqlite .venv/bin/python -m unittest discover -s tests -v
npm run build
.venv/bin/python -m compileall -q backend tests
```

The automated suite uses temporary SQLite databases and mocked AI responses for deterministic workflow cases. Historical live-provider usage is separately identified in the Phase 2.3–3.3 evidence listed above.
