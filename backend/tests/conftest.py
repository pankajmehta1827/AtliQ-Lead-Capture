import os
import sys
from pathlib import Path

import pytest

# Tests run against SQLite in rules mode (no LLM key, no Postgres needed).
TEST_DB = Path(__file__).parent / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["GROQ_API_KEY"] = ""
os.environ["REFERENCE_DATE"] = "2026-07-10"
os.environ["APP_ACCESS_CODE"] = ""
os.environ["SEED_ON_STARTUP"] = "true"
os.environ["WORKER_POLL_SECONDS"] = "3600"  # tests drive processing explicitly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client():
    if TEST_DB.exists():
        TEST_DB.unlink()
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        c.headers.update({"X-User": "Jay"})
        yield c
    engine.dispose()
