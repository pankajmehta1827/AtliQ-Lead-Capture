# AtliQ Lead Capture & Follow-up Assistant

An AI assistant for AtliQ Technologies' founder-led sales team. It reads sales conversations (email threads,
meeting notes, shared LinkedIn chats), drafts CRM records and updates with the evidence for every field, detects
follow-up signals, and shows each deal owner what to chase next, with live timers.

**Two rules hold throughout:**

- **Nothing reaches the CRM until the deal owner confirms it.**
- **The assistant never contacts a client.**

Built from the *AtliQ Lead Capture and Follow-up Assistant: AI PRD v1.0*.

| Layer | Tech |
|---|---|
| Frontend | React 18 + TypeScript (Vite) |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 |
| AI | LangGraph capture pipeline + LangChain structured output on **Groq** (`openai/gpt-oss-120b`, configurable) |
| Database | PostgreSQL (SQLite for the no-Docker local run) |
| Deployment | Railway: one Docker service plus Railway PostgreSQL |

---

## What it does

| Screen | What you can do |
|---|---|
| **Dashboard** | KPI cards (deals to follow up, new leads in the last 7 days, drafts to review, % of deals with a next step), a follow-up queue with one row per deal, a **live timer** and **Draft reply**, pipeline by stage, and insights such as *"FinEdge Bank ($95k) is going cold"* |
| **Ask AI** | Ask your pipeline in plain English (*"What's blocking FinEdge?"*, *"Which proposals have had no reply for 30 days?"*). Answers come only from the CRM and saved conversations, with linked deals and quotes, and unverified quotes are flagged |
| **Review queue** | AI drafts waiting for the owner. Click any field to highlight the sentence it came from. Choose which CRM record to update or create a new lead, edit, then **Confirm** or **Discard**. Drafts split out of an internal meeting are tagged *From internal meeting* |
| **Pipeline** | Two views of the open deals, switched with **Board / Queue** (the choice is remembered). **Board:** health cards (deals with a next step, new leads logged in 24h, drafts approved as written, value at risk), search, owner filter (including *Unassigned*) and *Needs attention only*, then one column per stage (New, Contacted, Proposal Sent) with its total value and attention bar. Deal cards show owner, days idle, next step and flags; **Assign owner** and **Add next step** save right from the card, logged like any deal edit. **Queue:** proposals awaiting a reply with **Draft reply**, deals without an owner with an owner picker, other deals missing a next step, and flagged value by owner |
| **CRM** | Every lead (open, won and lost) with where it came from (*CRM export / AI capture / Manual / Import*), an **AI Lead app → CRM** sync panel, Add lead with a duplicate check, CSV/Excel import and export |
| **AI Capture** | Paste an email, meeting note or LinkedIn chat; upload files; sync the sample mailbox and calendar; **Re-run with AI** for drafts made without a key |
| **Follow-ups** | One card per deal with a live **Due in / Overdue by** timer (green, amber, or red and pulsing), most overdue first. **Draft reply** / Done / Snooze / Dismiss. *Revisit date* reminders come from the date detector |
| **Daily summary** | New drafts, due follow-ups and deals going cold, per owner or for the whole team |
| **Settings & log** | Exclusion rules, a pause-processing switch, and the append-only log of every action |

## How it works

```
capture (paste / upload / sample mailbox + calendar sync)
   │  queued: nothing is lost if the LLM is down or rate-limited (retried; waits for Groq's retry-after)
   ▼
LangGraph:  check_exclusions → mask → classify → extract → ground → dates → match → assess → (cross_sell)
               │ excluded            │ └ internal note about several deals → multi_extract (one draft per deal)
               │                     │ not sales: skip, wipe content, log
   ▼
Draft in the owner's review queue (fields + verbatim evidence + confidence + duplicate candidates + follow-ups)
   ▼  owner confirms / edits / discards       ← the ONLY path that writes to the CRM
CRM deal created or updated · reminders scheduled · cross-sell ideas stored · every action audit-logged
```

**Where the AI is used:** every call uses strict JSON-schema output on Groq, and every client-specific fact must
quote its source.

In the capture pipeline (automatic, per conversation):

1. **Classify** the conversation: new lead, existing deal, existing client, *internal note about several deals*,
   or not sales.
2. **Extract** the CRM fields, a 3-5 sentence summary, follow-ups with dates, and new client needs.
3. **Date detector:** a focused pass for revisit dates and deferrals the extraction can miss ("check back around
   Q2 2026", "decision deferred to the 14 July board"). They become *Revisit date* reminders.
4. **Internal meeting notes:** a pipeline review that discusses several deals becomes **one update draft per
   deal**, matched to the right CRM record. Unknown companies become new-lead drafts.
5. **Cross-sell** ideas, for existing clients only, using that client's own history.

On demand (read-only: never writes to the CRM or contacts anyone):

6. **Draft reply:** a short follow-up email written from the deal's CRM record and latest conversations. You edit
   it, then copy it or open it in your own email app. Facts the AI can't quote from the records are flagged.
7. **Ask your pipeline:** answers questions across all deals, preferring the newest conversation over stale CRM
   notes, with deal links and checked quotes.

If Groq returns malformed JSON, the call is retried once. Rate limits and AI errors show as a clear message.

**Done in plain code, not AI:**

- **Masking:** card and bank numbers, passwords, API keys, Aadhaar and PAN are hidden before the model sees anything.
- **Grounding:** any value whose quote isn't in the source is dropped, so missing values stay empty.
- **Duplicate matching** by email, domain, company name, cited lead ID, with a referral guard.
- **Reminder rules** and the **priority score**.

### How follow-ups and timers are decided

| Source | Rule | Timer deadline |
|---|---|---|
| AI, from the conversation | Commitments and deadlines ("SOW by 15 July"), each with a quote | Its date |
| AI date detector | Revisit dates and deferrals ("check back around Q2 2026") become *Revisit date* reminders | Its date |
| AI, internal meeting note | A dated action for one of the deals it discusses | Its date |
| Rule | Client wrote last and AtliQ hasn't replied | Message date + 2 days |
| CRM scan | Status *Proposal Sent* and no contact for 7+ days | Last contact + 7 days |
| CRM scan | No contact for 14+ days | Last contact + 14 days |
| CRM scan | No next step recorded | Last contact + 2 days (grace period) |

AI-detected follow-ups become reminders when the owner confirms the draft. CRM-scan reminders are created every
30 minutes. The **priority score** (0-99) is the signal type plus 2 points per day overdue (up to +20) plus 1 point
per $5k of deal value (up to +18). *Hot* is 75 or more, *Warm* is 55-74.

---

## Run it

### Docker (recommended: PostgreSQL, same as production)

```bash
cp backend/.env.example backend/.env      # then set GROQ_API_KEY (use a key created for this project)
docker compose up -d --build              # http://localhost:8000
```

### Without Docker (SQLite)

```bash
cd frontend && npm install && npm run build
cd ../backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # bin/pip on macOS/Linux
.venv/Scripts/python run_local.py                                                       # http://localhost:8000
```

### Dev mode (hot reload)

```bash
cd backend && .venv/Scripts/uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev                                            # http://localhost:5173 (proxies /api)
```

Sign in by choosing a seller (Bhavin, Dhaval, Karandeep or Jay). On a public URL, set `APP_ACCESS_CODE` and the
login asks for it.

**Without `GROQ_API_KEY`** the pipeline runs in *rules mode*: conservative extraction where every draft is marked
"needs review". Add a key later, then use **AI Capture → Re-run with AI** to replace those drafts.

### Configuration (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local PostgreSQL | Railway's `postgres://` URL is converted automatically |
| `GROQ_API_KEY` | none | Enables AI mode |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Any Groq chat model; gpt-oss models use strict JSON-schema output |
| `REFERENCE_DATE` | today | Set `2026-07-10` so the sample dataset behaves realistically |
| `APP_ACCESS_CODE` | empty | Shared access code for hosted demos |
| `SELLERS` | `Bhavin,Dhaval,Karandeep,Jay` | Users who own deals |
| `PROCESSING_ENABLED` | `true` | Pause switch: `false` stops processing, and items wait in the queue |

**Groq limits:** the free tier allows about 200k tokens a day for gpt-oss-120b, roughly 40-60 conversations. The
worker waits and resumes when rate-limited. Use the Dev tier (pay-as-you-go) for real volumes.

---

## Deploy to Railway

1. **New Project → Deploy from GitHub repo →** this repository. It builds from `Dockerfile`, and `railway.json`
   sets the health check to `/api/health`.
2. **+ New → Database → PostgreSQL** in the same project.
3. Set these variables on the app service:
   - `DATABASE_URL=${{Postgres.DATABASE_URL}}`
   - `GROQ_API_KEY=<this project's key>`
   - `APP_ACCESS_CODE=<shared code>`. Required on a public URL.
   - Optional: `GROQ_MODEL`, `REFERENCE_DATE=2026-07-10` (dataset demo), `SELLERS`, `PROCESSING_ENABLED`
4. **Settings → Networking → Generate Domain.**

Keep **1 replica**: the capture worker and reminder scheduler run in the same process.

---

## Sample dataset

`backend/data/` holds the synthetic AtliQ dataset:

- `crm_export.csv`: 40 leads, seeded into the CRM on first start
- 34 email threads and 16 meeting notes
- `service_catalogue.json`: used for cross-sell suggestions

**AI Capture → Sync sample mailbox & calendar** runs every conversation through the pipeline. The dataset's
italic editorial notes (`*(No reply sent…)*`) are the answer key, so they're stripped before the model sees anything.

## Tests and evals

```bash
cd backend && .venv/Scripts/python -m pytest -q          # 23 tests: SQLite + rules mode, no network
cd backend && .venv/Scripts/python -m evals.run_evals    # PRD evals on the 50 labelled items (add N to limit)
```

`evals/labels.json` labels each dataset item with the CRM record it belongs to, `new` (missing from the CRM), or
`not_sales`. Rules-mode baseline: sales detection 94% precision / 100% recall; record matching 100% with 0 wrong
merges.

## Project layout

```
backend/
  app/
    graph/          LangGraph pipeline, prompts, schemas, grounding, rules-mode fallback
    routers/        capture, drafts (review queue), deals + reminders, crm, admin (config, exclusions, audit, metrics)
    services/       capture queue + worker, review (the only CRM writer), pipeline health + reminders, seed/import
    matching.py     duplicate / record matching        masking.py   sensitive-data masking
  data/             sample dataset + service catalogue
  evals/            labels + eval runner
  tests/            pytest suite
  run_local.py      no-Docker runner (SQLite)
frontend/src/
  pages/            Dashboard, ReviewQueue, Pipeline (stage board + action queue), CRM, Capture, Reminders (Follow-ups), Summary, Settings, DealDetail
  components/       DealTimer (live timers), SourceView (evidence highlight), ui (icons)
Dockerfile · docker-compose.yml · railway.json
```

## Running cost (LLM only)

About 4,070 input and 1,180 output tokens per conversation (classify + extract + cross-sell share), at 100
conversations a day:

| Model | Per conversation | Per month |
|---|---|---|
| **openai/gpt-oss-120b** (Groq, used) | $0.0014 | ~$3 |
| openai/gpt-oss-20b (Groq) | $0.0007 | ~$1.60 |
| qwen/qwen3.8-27b (Groq, preview) | $0.0088 | ~$19 |
| Claude Haiku 4.5 (Anthropic) | $0.0109 | ~$24 |

List prices as of October 2026. Hosting is excluded.

## Known gaps (before real client data)

- **Connectors:** email and calendar arrive through paste, upload or the sample sync. Read-only Gmail/Outlook and
  calendar connections are the next build item. LinkedIn is share-only (no scraping), by design.
- **Identity:** a user picker plus a shared access code. Replace with SSO and role-based access.
- **Notifications:** reminders and the daily summary appear in the app only; there's no email or Slack delivery yet.
- **AI quality:** vague revisit dates ("check back around Q2") are sometimes missed; internal multi-deal meeting
  notes can produce empty drafts; deals with no owner produce reminders nobody sees under "Mine".
- **Data handling:** retention, deletion and data residency still need the legal decisions listed in the PRD.
