"""Test setup.

By default tests run on a throw-away SQLite file (fast, no services needed).
Set TEST_DATABASE_URL=postgresql+psycopg://... to run the same suite on PostgreSQL + pgvector.
"""
import os
import secrets
import tempfile

_tmp = tempfile.mkdtemp(prefix="novalearn-tests-")
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["STORAGE_DIR"] = os.path.join(_tmp, "storage")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.sqlite"
# Tests are deterministic and must never consume configured hosted-provider quota.
os.environ["LLM_PROVIDER"] = "none"
os.environ["EMBEDDING_PROVIDER"] = "local-hash"
os.environ["STT_PROVIDER"] = "none"
os.environ["VISION_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.ratelimit import auth_limiter  # noqa: E402
from app.database.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    if engine.dialect.name == "postgresql":
        with engine.begin() as c:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    auth_limiter.reset()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _register(client: TestClient, email: str, name: str = "Test User") -> dict:
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def alice(client):
    return _register(client, "alice@example.com", "Alice")


@pytest.fixture
def bob(client):
    return _register(client, "bob@example.com", "Bob")


@pytest.fixture
def course(client, alice):
    r = client.post("/api/courses", json={"title": "Thermodynamics"}, headers=alice)
    assert r.status_code == 201
    return r.json()


# ---------- shared helpers for Stage 3 tests ----------
from app.tests import samples  # noqa: E402

THERMO_PDF = [
    "The first law of thermodynamics states that energy is conserved. Heat added to a system equals the change in internal energy plus the work done.",
    "Entropy measures disorder. The second law says entropy of an isolated system never decreases.",
    "The Carnot cycle is the most efficient heat engine. Carnot efficiency depends only on the reservoir temperatures.",
]


def upload(client, headers, course_id, name, data):
    r = client.post(f"/api/courses/{course_id}/documents", headers=headers, files={"file": (name, data, "application/octet-stream")})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def thermo(client, alice, course):
    """A course with a real PDF, a real PPTX and a real timestamped transcript, all indexed."""
    cid = course["id"]
    pdf = upload(client, alice, cid, "thermo_notes.pdf", samples.make_text_pdf(THERMO_PDF))
    pptx = upload(client, alice, cid, "week3.pptx", samples.make_pptx(["Heat engines", "Refrigerators"], notes={1: "Engines convert heat into work."}))
    vtt = upload(client, alice, cid, "lecture.vtt", samples.VTT)
    for d in (pdf, pptx, vtt):
        assert client.get(f"/api/documents/{d['id']}", headers=alice).json()["job"]["status"] == "indexed"
    return {"course": course, "pdf": pdf, "pptx": pptx, "vtt": vtt}
