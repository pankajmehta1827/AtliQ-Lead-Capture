# AtliQ Lead Capture & Follow-up Assistant

V1 implementation of `Prd/AtliQ Lead Capture and Follow-up Assistant - AI PRD v1.0`.
An AI assistant that reads sales conversations (email, meeting notes, shared LinkedIn messages), drafts CRM records
and updates, detects follow-up signals, reminds the deal owner, and shows pipeline health. **The deal owner confirms
every record before it reaches the CRM, and the assistant never contacts a client.**

| Layer | Tech |
|---|---|
| Frontend | React 18 + TypeScript (Vite) |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 |
| AI | LangGraph capture pipeline + LangChain structured output on **Groq** (`openai/gpt-oss-120b`, configurable) |
| Database | PostgreSQL |
| Deployment | Railway (one Docker service + Railway PostgreSQL) |

## How it works

```
capture (email / meeting / LinkedIn share / file upload / dataset sync)
   │  queued in source_items (nothing lost if the LLM is down: retried, then flagged)
   ▼
LangGraph:  check_exclusions → mask_sensitive → classify → extract → ground → match → assess → (cross_sell)
               │ excluded            │ not sales: skip, wipe content, log
   ▼
Draft in the owner's review queue (fields + verbatim evidence + confidence + duplicate candidates + follow-ups)
   ▼  owner confirms / edits / discards       ← the ONLY path that writes to the CRM
CRM deal created or updated · reminders scheduled · cross-sell ideas stored · every action audit-logged
```

| PRD requirement | Where |
|---|---|
| FR-2 classify sales vs not | `graph/pipeline.py: classify` (Groq) |
| FR-3 extract fields | `graph/pipeline.py: extract`, schemas in `graph/schemas.py` |
| FR-4 review queue, save only on confirm | `services/review.py`, Review queue page |
| FR-5 duplicate matching | `matching.py` (deterministic: email, domain, fuzzy name, cited lead id, referral guard) |
| FR-6 follow-up reminders | extraction follow-ups + "client awaiting reply" + `services/pipeline_health.py` scanner (proposal unanswered 7d, inactive 14d, no next step, follow-up date reached) |
| FR-7 pipeline dashboard | `/api/deals`, Pipeline page (flagged first) |
| FR-8 source links | every field carries a verbatim quote; `graph/grounding.py` drops values whose quote is not in the source; UI highlights it |
| FR-9 action log | `audit_log` table (append-only, no edit/delete API), Settings & log page |
| FR-10 exclusions | email / domain / subject / keyword rules; matching items are skipped and their content wiped |
| FR-11 cross-sell | `crosssell` node — uses only the same client's history + `data/service_catalogue.json` |
| FR-12 LinkedIn | one-click share via the Capture page (no scraping) |
| FR-13 daily summary | `/api/summary/daily`, Daily summary page |
| Guardrail: sensitive data | `masking.py` masks cards, IBAN/bank accounts, IFSC, passwords/OTP, API keys, Aadhaar, PAN before the LLM and before storage |
| Kill switch | Settings → Pause processing (`PROCESSING_ENABLED`) |
| Success metrics | `/api/metrics`, tiles on the Pipeline page |

**Rules mode:** without `GROQ_API_KEY` the pipeline falls back to conservative rule-based extraction (every draft is
marked "needs review"), so the app, tests and demo run offline.

## Dataset

`backend/data/` is a copy of the project's `Dataset/` folder (`crm_export.csv`, 34 email threads, 16 meeting notes) plus
`service_catalogue.json`, which I added for cross-sell. On first start the CRM export is seeded into PostgreSQL. On the
Capture page, **Sync sample mailbox & calendar** feeds every email and meeting note through the pipeline, the way the
real mailbox and calendar connectors would. The dataset's italic editorial notes (`*(No reply sent…)*`) are ground
truth, so they are stripped before the model sees anything. Set `REFERENCE_DATE=2026-07-10` so "today" matches the dataset.

## Run locally

Full stack with Docker (PostgreSQL included):

```bash
docker compose up --build
```

Open http://localhost:8000. To enable the AI, put `GROQ_API_KEY=...` in `backend/.env`, using a key created for this
project only.

Dev mode (hot reload). You need a running PostgreSQL, e.g. `docker compose up db`:

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (bin/pip on macOS/Linux)
cp .env.example .env                                                                  # set GROQ_API_KEY
.venv/Scripts/uvicorn app.main:app --reload --port 8000
cd ../frontend && npm install && npm run dev                                          # http://localhost:5173
```

### Without Docker (SQLite)

```bash
cd frontend && npm install && npm run build
cd ../backend && .venv/Scripts/python run_local.py      # http://localhost:8000
```

`run_local.py` serves the React build and stores data in `backend/atliq_local.db` (SQLite) instead of
PostgreSQL; set `LOCAL_DATABASE_URL` to use a PostgreSQL server instead. The Groq key and other settings still
come from `backend/.env`.

## Tests and evals

```bash
cd backend && .venv/Scripts/python -m pytest -q        # SQLite + rules mode, no network
cd backend && .venv/Scripts/python -m evals.run_evals  # PRD evals on the 50 labelled dataset items
```

`evals/labels.json` labels every dataset item with the CRM record it belongs to, `new` (lead missing from the CRM),
or `not_sales` (internal multi-deal discussion). Current **rules-mode** baseline:

- Sales detection: 94% precision, 100% recall. The 3 internal meetings need the LLM to be recognised.
- Record matching: 100%, with 0 wrong merges.

Run the evals with `GROQ_API_KEY` set to measure the AI path before alpha.

## Deploy to Railway

1. Push this folder to GitHub. In Railway: **New Project → Deploy from GitHub repo**, and set the service's
   **Root Directory** to `AtliQ Lead Capture`. It builds from `Dockerfile`, and `railway.json` sets the health check
   `/api/health`.
2. **+ New → Database → PostgreSQL** in the same project.
3. On the app service, set these variables:
   - `DATABASE_URL=${{Postgres.DATABASE_URL}}` (the app converts it for psycopg 3)
   - `GROQ_API_KEY=<this project's key>`
   - `APP_ACCESS_CODE=<shared code>`. Required on a public URL; the login asks for it.
   - Optional: `GROQ_MODEL`, `REFERENCE_DATE=2026-07-10` (for the dataset demo), `SELLERS`, `PROCESSING_ENABLED`
4. **Settings → Networking → Generate Domain.**

Or from the CLI: `railway init`, `railway add --database postgres`, `railway up`.

Keep **1 replica**: the capture worker and reminder scheduler run in-process.

## Known gaps vs the PRD (before real client data)

- **Identity:** pick-a-user + shared access code. Replace with SSO and role-based access (NFR: Security).
- **Connectors:** the mailbox and calendar connector is simulated by the dataset sync, file upload and paste. Real
  Gmail/Outlook and calendar OAuth (read-only) is the next build item. The CRM is this app's own PostgreSQL schema
  until the open question "which CRM does AtliQ use?" is answered.
- **Notifications:** reminders and the daily summary are in-app only. There is no email/Slack delivery yet.
- **Data handling:** retention and deletion of processed data and data-residency settings still need the
  Legal/compliance decisions listed in the PRD's open questions.
