"""Run the whole app on this machine without Docker or PostgreSQL.

    python run_local.py            -> http://localhost:8000

Uses a local SQLite file (backend/atliq_local.db) instead of PostgreSQL, and serves the React build from
frontend/dist. Everything else (Groq key, model, reference date) comes from backend/.env as usual.
Set LOCAL_DATABASE_URL to point at a real PostgreSQL instead.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
DIST = BACKEND.parent / "frontend" / "dist"
STATIC = BACKEND / "static"

# Environment variables take precedence over backend/.env in the app's settings.
os.environ["DATABASE_URL"] = os.environ.get("LOCAL_DATABASE_URL", f"sqlite:///{(BACKEND / 'atliq_local.db').as_posix()}")

if DIST.exists():
    # main.py serves ./static; refresh it from the latest `npm run build`
    shutil.rmtree(STATIC, ignore_errors=True)
    shutil.copytree(DIST, STATIC)
else:
    print("frontend/dist not found: run `npm run build` in frontend/ first (API will still start).", file=sys.stderr)

if __name__ == "__main__":
    import uvicorn

    sys.path.insert(0, str(BACKEND))
    port = int(os.environ.get("PORT", "8000"))
    print(f"AtliQ Lead Assistant on http://localhost:{port}  (database: {os.environ['DATABASE_URL']})")
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, app_dir=str(BACKEND))
