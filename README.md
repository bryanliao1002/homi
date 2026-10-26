# homi.

**Better Living. Less Drama.** A shared home for roommate coordination and a calm, neutral AI household companion.

The app includes a welcome screen, a seeded demo home, household creation, persistent SQLite household data, switchable demo profiles, a responsive dashboard, the House Board, editable chores, shared expense tracking, approved house rules, and Little Homi. Ask homi. supports staged, multi-agent household mediation with independent roommate approvals.

## Run locally

Requirements: Node.js 20 or newer and Python 3.11 or newer.

1. In the project folder, install the frontend packages:

   ```bash
   npm install
   ```

2. Create and activate a Python virtual environment, then install the backend packages:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

3. For AI features, copy `.env.example` to `.env` and add the university-provided key locally:

   ```bash
   cp .env.example .env
   ```

   Add `PORTKEY_API_KEY=...` to `.env` using a local editor. Never commit `.env`. homi. uses only `gpt-6-luna` through Portkey. Chores and expense tracking work without an API key.

4. Start the API in one terminal:

   ```bash
   npm run backend
   ```

5. Start the website in a second terminal:

   ```bash
   npm run dev
   ```

6. Open [http://127.0.0.1:5173](http://127.0.0.1:5173).

The API runs at `http://127.0.0.1:8000`; its health check is `/api/health`. SQLite creates or migrates `backend/data/homi.sqlite` the first time the backend starts. The database is local and excluded from Git.

## Demo and household data

Choose **Try the demo** to open the seeded Willow House with four switchable roommate profiles, sample announcements, chores, expenses, approved rules, and notifications. The demo profile choice is stored in this browser. Use **Create a household** to save a new household and its roommate names to the local SQLite database. Board posts, chore creation/edits/completion, expenses, and share payment status persist there.

There is no production sign-in, external notifications, or payment processing. Demo profile switching is not authentication: anyone with browser access can choose any roommate profile. “Mark my share paid” records a household status only; it does not transfer money or verify payment. The House Rules and Ask homi. AI features send only the text submitted to their workflows to the backend AI service.

## Chores and shared expenses

The Chores page supports adding a task, assigning a roommate, setting a due date and room, editing, deleting, and toggling completion. Dashboard summaries use the latest household state returned by the backend.

Bills & Rent supports equal or custom per-roommate shares, a selected payer, optional due dates, per-share payment status, household outstanding totals, and each profile's amount owed and amount owed to them. The backend uses integer cents as its calculation source of truth. Equal splits assign leftover cents in a stable household-member order; custom shares must add up to the exact total. Existing seeded bills are migrated to cent-based shares on startup. Marking a share paid is a record-keeping action only, not a payment. Profile selection cannot prove who recorded it.

## Fresh-clone setup

From a new clone, run these commands from the project folder (Node.js 20+ and Python 3.11+):

```bash
npm ci
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env  # optional; add PORTKEY_API_KEY locally for AI features
npm run backend        # terminal 1
npm run dev            # terminal 2
```

Open `http://127.0.0.1:5173`. SQLite initializes automatically and the demo household is seeded locally. Core household, chore, and expense features work without an API key; AI routes require `PORTKEY_API_KEY`. If Python imports fail, confirm the virtual environment is active and install `requirements.txt`. Never paste a real key into a browser, issue, or evidence file.

## Product screenshots

These reviewed screenshots show the current demo interface. They use seeded demo profiles and household data.

- [Welcome screen](evidence/final-screenshots/public/welcome.png)
- [Dashboard](evidence/final-screenshots/public/dashboard.png)
- [House Rules](evidence/final-screenshots/public/house-rules.png)
- [House Board](evidence/final-screenshots/public/house-board.png)
- [Ask homi.](evidence/final-screenshots/public/ask-homi.png)
- [Chores](evidence/final-screenshots/public/chores.png)
- [Bills & Rent](evidence/final-screenshots/public/bills-rent.png)

## Phase 2.1 AI connection

The backend-only AI client uses the university `PORTKEY_API_KEY` from `.env` at the project root or its parent, and requests `gpt-6-luna`. It calls Portkey's Responses API at `https://api.portkey.ai/v1/responses` with the key in the `x-portkey-api-key` header and the structured `input_text` format. The gateway may return the response model label `gpt-6-luna-global`. The key and request/response text are never written to the browser or usage log.

To make one minimal live connectivity check, run `python -m backend.verify_ai` from the project folder after activating the Python environment. The check prints the actual model response, returned usage counts, and latency. Usage metadata and sanitized errors are stored in the local SQLite `ai_usage_logs` table; token fields remain empty if the provider omits them. Requests have a timeout, input/output bounds, and a small in-process rate limit.

The AI service supports the documented GPT-6 Luna reasoning efforts. The `/api/health` response reports the requested model, whether the server has a key configured, and the supported effort names. House Board analysis is integrated in Phase 2.4 below.

## Phase 2.2 AI House Rules

Roommates save preferences by category on the House Rules page. After at least two roommates contribute, Little Homi uses `gpt-6-luna` with `high` reasoning effort to draft practical rule proposals. The app shows each draft and the profile that has responded. Roommates can approve, reject, or request a change with a note; requested changes can be sent back through the same AI agent for a fresh draft. Every revised draft starts a new approval round.

All household members are required approvers for each household-wide rule. The backend stores preference, proposal, vote, and active-rule records in SQLite. In a single SQLite transaction, it activates a rule only after it verifies that every current household member has a corresponding approval record and every required decision is `approved`. Rejections and change requests never activate a rule.

AI usage metadata is stored in `ai_usage_logs`; per-run agent details are stored in `ai_agent_runs`. These include requested and returned model labels, reasoning effort, token counts when supplied, request ID, API latency, end-to-end agent latency, operation/version, participant and preference counts, proposal count, and sanitized outcome/error codes. Prompts and API keys are not logged. The local database stays excluded from Git.

The app still has no sign-in. The demo profile switcher lets roommates act under separate household profiles, while the backend checks that each submitted profile belongs to the household and is on that proposal's required-approver list. A production deployment would need authenticated member identities to establish who cast each vote.

## Phase 2.3 AI mediation

Ask homi. guides each case through five steps: tell Homi, hear everyone, find common ground, review an agreement, and confirm together. The Listening Agent (medium effort) summarizes claims and uncertainties and asks clarifying questions. Each selected roommate submits one immutable perspective; every active clarification must be answered or explicitly marked unknown before mediation can proceed. The Mediation Agent (high effort) retrieves approved House Rules and relevant active agreements from SQLite, compares the submitted perspectives, and proposes a balanced next step. The Agreement Agent (medium effort) turns that plan into participant-linked responsibilities, deadlines, and follow-up.

All three agents use the backend Portkey service and only request `gpt-6-luna`. JSON-mode prompts explicitly request JSON as required by the gateway. API token counts, reasoning tokens when returned, response model label, effort, latency, errors, request IDs, and agent runs are recorded in SQLite. Agent tool traces contain counts and operation names, not roommate text.

Statements and clarification responses are visible only in the current profile's case view; the mediation summary and pending agreement are shared with involved participants. Identity hiding masks names where possible, but it cannot guarantee anonymity because roommates can switch demo profiles and infer identities from details. The profile switcher is not authentication. Anyone with access to the browser can act as another demo profile. Do not use this demo for sensitive disclosures.

For threats, harassment, abuse, or safety concerns, a local safety screen pauses normal mediation and shows support guidance without sending that case through the agents. This is a basic keyword-based screen, not a safety service or emergency response system.

Only selected case participants can approve. Each participant can record one immutable decision per proposal version. Rejection or a change request blocks activation; a revision creates a new version with a fresh approval round. The backend activates an agreement in a SQLite transaction only after it confirms an approval from every required participant. This demo still cannot prove who cast a vote; production use needs authenticated accounts.

## Phase 2.4 Smart House Board

House Board posts are analyzed by the backend Smart Board agent using `gpt-6-luna` with medium reasoning effort. The agent classifies the post, prepares a concise summary, extracts only source-grounded details, compares the message with active approved rules retrieved from SQLite, and asks for clarification when a missing detail could change the interpretation. User text is treated as untrusted input. The model's assessment is advisory; it cannot grant permission.

The agent uses a 2,048 output-token first attempt. If Portkey returns an HTTP 200 incomplete response specifically because that cap was reached, it retries once with a 3,072-token cap. Other provider errors are not retried. Both attempts use the same agent run ID and are logged individually. The request and approvals are saved only after a complete response validates. If analysis remains unavailable, the original post is still shared with an explicit unavailable status and no approval is inferred. Authors can start a fresh version to retry; prior roommate responses do not carry over.

Requests and rule conflicts open a versioned approval round for every other current household member. Each profile can approve, decline, or request a change once. The backend marks the request approved only after it verifies all required current-version approvals. Rejection or requested changes block approval. Revisions clear the prior decisions and start a new round. In-app notifications are deduplicated, scoped to relevant profiles, linked to the Board post, and support read/unread status. No email, SMS, or push notification is sent.

Agent traces record tool names, rule/member counts, validation results, retry budgets, and outcome codes without storing post text. Usage logs retain the actual model label, effort, token counts when returned, latency, and sanitized errors. The demo profile switcher is not authentication; it cannot verify who cast a vote and is not production access control.

## Verification

Run the isolated backend workflow tests with:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Build the frontend with `npm run build`. The workflow tests cover House Board summaries, approved-rule retrieval, clarification, AI failure fallback, output-limit retry behavior, approval gating, revisions, notification scoping, injection handling, and mediation privacy/approval/safety behavior. Tests use mocked model responses and do not invent provider usage. Live usage is recorded only when real calls are made.

Sanitized Phase 2.4 browser and API evidence is in [evidence/phase24-workflow.json](evidence/phase24-workflow.json). It contains actual usage metadata and workflow outcomes, without prompts, household statements, or credentials.

## Phase 3.1 integration QA

Run the regression suite, production build, and Python syntax check from the project folder:

```bash
.venv/bin/python -m unittest discover -s tests -v
npm run build
.venv/bin/python -m compileall -q backend tests
```

The Phase 3.1 regression run had 18 workflow tests. Model calls in repeatable tests are mocked; live API verification is reported separately. For a browser pass, start the backend and Vite using the local run steps above, then check household creation and refresh persistence, profile switching, dashboard modules and feature routes, House Rules → House Board, notifications and approvals, the three mediation agents, chores CRUD, and shared expenses. The normal local development URL is `http://127.0.0.1:5173`.

Sanitized results, live usage totals, verified cross-feature scenarios, incomplete features, and the browser limitation are in [evidence/phase31-integration.json](evidence/phase31-integration.json). The browser run found no console errors. Chrome reported one low-priority autofill suggestion for the labeled profile selector; it remains usable and accessible. Browser screenshots could not be exported automatically in this run and require manual capture if image evidence is needed.

## Phase 3.2 AI safety and reliability

The focused adversarial suite and regression results, tested safeguards, remaining limitations, local smoke check, and sanitized live-call usage are recorded in [evidence/phase32-safety/REPORT.md](evidence/phase32-safety/REPORT.md). Machine-readable provider metadata with no prompts or response text is in [evidence/phase32-safety/live-ai-usage.json](evidence/phase32-safety/live-ai-usage.json). Reproduce the automated checks with the commands in the Verification section; the Phase 3.2 run completed 26 tests with no failures and a successful frontend production build. Three synthetic live probes used only `gpt-6-luna`; costs were not estimated.

## Phase 3.3 Tokenomics and impact

Phase 3.3's sanitized SQLite usage export, deduplicated evidence reconciliation, component metrics, public-rate cost model, paired context-reduction experiment, fictional-scenario evaluation, and pilot questionnaire are documented in [evidence/phase33/phase33-summary.md](evidence/phase33/phase33-summary.md). Recompute aggregate CSVs from the preserved row-level metadata with `evidence/phase33/export_usage.py` and `evidence/phase33/summarize_phase33.py`. The pricing figures are illustrative public OpenAI rates; university Portkey billing was not available for verification. No human pilot results are claimed.

## Phase 3.4 Household workflows

Chores and shared-expense behavior, migration details, cent rounding, demo-profile limitations, and current regression results are indexed in [evidence/INDEX.md](evidence/INDEX.md). Re-run the full suite, production build, and Python checks with:

```bash
HOMI_DATABASE_PATH=/private/tmp/homi-tests.sqlite .venv/bin/python -m unittest discover -s tests -v
npm run build
.venv/bin/python -m compileall -q backend tests
```

The test database path is disposable; workflow tests also use temporary isolated SQLite files. The public source repository is [github.com/bryanliao1002/homi](https://github.com/bryanliao1002/homi).

Never put API keys in frontend code or commit a real `.env` file. `.env` and `.env.*` files are ignored by `.gitignore`; `.env.example` contains only a blank placeholder. SQLite databases and sidecar files are ignored as well.
