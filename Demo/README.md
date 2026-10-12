# Demo records

The conversations used in the stakeholder demo video, copied from the golden set (`Dataset/golden`) so the
demo can be run on its own. Use them with the narration script and click path in `docs/08 …`.

| File | Golden id | Used at | What it shows |
|---|---|---|---|
| `1_G-013_vertex_check_back_october.md` | G-013 | 0:45, pasted live | A "check back in October" email becomes a dated revisit reminder on the existing deal |
| `2_G-025_internal_weekly_sales_sync.md` | G-025 | 1:20, pasted live (Channel: Meeting notes) | One internal note becomes one update per deal, plus a new lead |
| `3_G-021_northwind_eta_prediction.md` | G-021 | 1:55, pasted live right after G-025 | Existing-client update with a cross-sell idea from that client's own history |
| `safety_G-028_personal_proposal_plans.md` | G-028 | 3:10, pre-loaded | Personal email full of sales words: skipped, content not stored |
| `safety_G-038_shopswift_vendor_registration.md` | G-038 | 3:10, pre-loaded | Password and bank details masked before the AI sees them |
| `ask_ai_questions.md` | A-010, A-012 | 2:50 and 3:10 | Grounded answer with quotes, and a refusal to guess |

The ShopSwift password and account number are made up for the test set.

## Run it locally

From the repository root (`AtliQ-Lead-Capture`), one time only:

```bash
cd frontend && npm install && npm run build && cd ..
pip install -r backend/requirements.txt
```

`backend/.env` holds the AI keys (copy `backend/.env.example` and fill it in if you don't have one). With
`LLM_PROVIDER=anthropic` and `EMAIL_PROVIDER=anthropic`, capture and email drafts run on Claude Haiku 5.5 and
Ask AI on Groq. Leave `APP_ACCESS_CODE` empty locally. The demo needs these keys: without them the app runs
in rules mode, which cannot tell that the personal email (G-028) is not sales, has no cross-sell ideas and no
Ask AI.

Start the app:

```bash
python backend/run_local.py
```

Open http://localhost:8000, choose **Jay**, then **Continue**. The CRM is seeded on first start
(`backend/atliq_local.db`).

In a second terminal, load the sample mailbox (needed for Ask AI A-010) and pre-load the two safety items:

```bash
python Demo/load_demo.py --sample --safety
```

Then follow the click path: paste the three numbered files on **Add conversation** during the recording.

### Rehearse, then start clean

Pasting the same text twice counts as the same conversation, so rehearse on a throwaway copy and reset it
before the real take:

```bash
python Demo/load_demo.py --sample --all
```

To start clean, stop the app (Ctrl+C), delete `backend/atliq_local.db`, and start it again.

### Recording on Railway instead

The live app works the same way. Set the access code in your shell without echoing it, then point the
loader at Railway:

```bash
python Demo/load_demo.py --url https://atliq-lead-capture-production.up.railway.app --safety
```

with `ATLIQ_ACCESS_CODE` set in that shell. Railway's sample mailbox is already synced, so `--sample` is not
needed there.
