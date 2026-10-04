from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from .config import get_settings
from .db import SessionLocal, engine, init_db
from .models import Deal
from .routers import admin, capture, crm, deals, drafts
from .services.capture import worker_loop
from .services.pipeline_health import scheduler_loop
from .services.seed import import_crm_csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("atliq")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    init_db()
    if s.seed_on_startup:
        with SessionLocal() as db:
            if not db.scalar(select(func.count()).select_from(Deal)):
                log.info("Seeding CRM from crm_export.csv: %s deals", import_crm_csv(db))
    log.info("LLM mode: %s", f"Groq {s.groq_model}" if s.llm_enabled else "rules (no GROQ_API_KEY)")
    stop = asyncio.Event()
    tasks = [asyncio.create_task(worker_loop(stop)), asyncio.create_task(scheduler_loop(stop))]
    yield
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="AtliQ Lead Capture & Follow-up Assistant", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (capture.router, drafts.router, deals.router, crm.router, admin.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


# Serve the built React app (copied into ./static by the Dockerfile) with SPA fallback.
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (STATIC_DIR / path).resolve()
        if path and candidate.is_file() and STATIC_DIR in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
