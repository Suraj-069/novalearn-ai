"""Topic hierarchy: automatic build, user corrections, prerequisites, LLM output validation."""
import json
import uuid

from sqlalchemy import func, select

from app.models.knowledge import ContentChunk, Topic, TopicPrerequisite
from app.services.knowledge.topics import build_topics_llm, rebuild_topics
from app.tests import samples
from app.tests.conftest import upload
from app.tests.fakes import FakeLLM


def topics(client, headers, cid):
    return client.get(f"/api/courses/{cid}/topics", headers=headers).json()


def test_topics_are_built_and_account_for_every_chunk(client, alice, thermo, db):
    ts = topics(client, alice, thermo["course"]["id"])
    total = db.scalar(select(func.count()).select_from(ContentChunk))
    assert len(ts) >= 2  # refined as more files arrived, not stuck with the single topic from the first file
    assert ts and sum(t["chunk_count"] for t in ts if t["parent_id"] is None) == total
    for t in ts:
        assert t["origin"] == "auto" and t["mastery"] is None  # mastery isn't guessed before any assessment
        assert t["prerequisites"] == []                        # heuristic mode never invents prerequisites
        assert t["documents"] and sum(t["source_counts"].values()) == t["chunk_count"]


def test_rebuild_is_deterministic(client, alice, thermo):
    cid = thermo["course"]["id"]
    assert client.post(f"/api/courses/{cid}/topics/rebuild", headers=alice).json()["method"] == "heuristic"
    first = sorted(t["name"] for t in topics(client, alice, cid))
    client.post(f"/api/courses/{cid}/topics/rebuild", headers=alice)
    assert sorted(t["name"] for t in topics(client, alice, cid)) == first  # same material => same topics


def test_user_edits_survive_a_rebuild(client, alice, thermo, db):
    cid = thermo["course"]["id"]
    mine = client.post(f"/api/courses/{cid}/topics", headers=alice, json={"name": "My exam focus"}).json()
    chunk = db.scalar(select(ContentChunk).where(ContentChunk.page_number == 2))
    client.patch(f"/api/chunks/{chunk.id}", headers=alice, json={"topic_id": mine["id"]})
    first = next(t for t in topics(client, alice, cid) if t["chunk_count"] > 0 and t["id"] != mine["id"])
    client.patch(f"/api/topics/{first['id']}", headers=alice, json={"name": "Renamed by me"})
    client.post(f"/api/courses/{cid}/topics/rebuild", headers=alice)
    db.expire_all()
    after = {t["name"]: t for t in topics(client, alice, cid)}
    assert "My exam focus" in after and "Renamed by me" in after
    assert after["Renamed by me"]["chunk_count"] >= 1  # the renamed topic kept its passages (not an empty shell)
    assert str(db.get(ContentChunk, chunk.id).topic_id) == mine["id"]  # the corrected assignment was kept


def test_deleting_a_topic_unassigns_its_chunks(client, alice, thermo, db):
    t = topics(client, alice, thermo["course"]["id"])[0]
    assert client.delete(f"/api/topics/{t['id']}", headers=alice).status_code == 204
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ContentChunk).where(ContentChunk.topic_id == uuid.UUID(t["id"]))) == 0


def test_circular_prerequisites_are_rejected(client, alice, thermo):
    cid = thermo["course"]["id"]
    a = client.post(f"/api/courses/{cid}/topics", headers=alice, json={"name": "A"}).json()
    b = client.post(f"/api/courses/{cid}/topics", headers=alice, json={"name": "B"}).json()
    assert client.post(f"/api/topics/{a['id']}/prerequisites", headers=alice, json={"prerequisite_id": b["id"]}).status_code == 201
    assert client.post(f"/api/topics/{b['id']}/prerequisites", headers=alice, json={"prerequisite_id": a["id"]}).status_code == 400
    assert client.post(f"/api/topics/{a['id']}/prerequisites", headers=alice, json={"prerequisite_id": a["id"]}).status_code == 400
    got = {t["name"]: t for t in topics(client, alice, cid)}
    assert got["A"]["prerequisites"][0]["name"] == "B" and got["A"]["prerequisites"][0]["origin"] == "user"


def test_topic_sources_return_real_locations(client, alice, thermo):
    t = max(topics(client, alice, thermo["course"]["id"]), key=lambda x: x["chunk_count"])
    src = client.get(f"/api/topics/{t['id']}/sources", headers=alice).json()
    assert src and all(s["filename"] and (s["page"] or s["slide"] or s["start_seconds"] is not None) for s in src)


def test_cannot_move_a_chunk_into_another_courses_topic(client, alice, thermo, db):
    other = client.post("/api/courses", json={"title": "Other"}, headers=alice).json()
    foreign = client.post(f"/api/courses/{other['id']}/topics", headers=alice, json={"name": "Foreign"}).json()
    chunk = db.scalar(select(ContentChunk))
    assert client.patch(f"/api/chunks/{chunk.id}", headers=alice, json={"topic_id": foreign["id"]}).status_code == 400


# ---------- LLM topic builder: output is validated, never trusted ----------
def _course_with_chunks(client, alice, course, db):
    upload(client, alice, course["id"], "a.pdf", samples.make_text_pdf(THERMO := [
        "Heat is energy transferred because of a temperature difference between two bodies.",
        "Entropy measures disorder and the second law says it never decreases in isolated systems.",
        "The Carnot cycle sets the maximum efficiency of any heat engine between two reservoirs."]))
    db.expire_all()
    return uuid.UUID(course["id"])


def _reset(db, cid):
    for c in db.scalars(select(ContentChunk).where(ContentChunk.course_id == cid)):
        c.topic_id = c.subtopic_id = None
    for t in db.scalars(select(Topic).where(Topic.course_id == cid)):
        db.delete(t)
    db.flush()


def test_llm_topics_with_subtopics_and_prerequisites(client, alice, course, db):
    cid = _course_with_chunks(client, alice, course, db)
    _reset(db, cid)
    reply = json.dumps({"topics": [
        {"name": "Heat", "description": "Basics", "chunks": [0], "subtopics": []},
        {"name": "Entropy", "description": "Second law", "chunks": [], "subtopics": [{"name": "Second law", "description": "d", "chunks": [1]}]},
        {"name": "Engines", "description": "Cycles", "chunks": [2], "subtopics": []}],
        "prerequisites": [{"topic": "Entropy", "requires": "Heat"}, {"topic": "Engines", "requires": "Entropy"}]})
    chunks = list(db.scalars(select(ContentChunk).where(ContentChunk.course_id == cid).order_by(ContentChunk.chunk_index)))
    assert build_topics_llm(db, cid, chunks, FakeLLM(reply)) is True
    db.flush()
    names = {t.name: t for t in db.scalars(select(Topic).where(Topic.course_id == cid))}
    assert {"Heat", "Entropy", "Engines", "Second law"} <= set(names) and names["Second law"].parent_id == names["Entropy"].id
    assert chunks[1].subtopic_id == names["Second law"].id and chunks[1].topic_id == names["Entropy"].id
    assert db.scalar(select(func.count()).select_from(TopicPrerequisite)) == 2


def test_llm_cyclic_prerequisites_are_dropped(client, alice, course, db):
    cid = _course_with_chunks(client, alice, course, db)
    _reset(db, cid)
    reply = json.dumps({"topics": [{"name": "A", "chunks": [0]}, {"name": "B", "chunks": [1]}],
                        "prerequisites": [{"topic": "A", "requires": "B"}, {"topic": "B", "requires": "A"}]})
    chunks = list(db.scalars(select(ContentChunk).where(ContentChunk.course_id == cid)))
    assert build_topics_llm(db, cid, chunks, FakeLLM(reply)) is True
    db.flush()
    assert db.scalar(select(func.count()).select_from(TopicPrerequisite)) == 0


def test_llm_garbage_falls_back_to_heuristic(client, alice, course, db):
    cid = _course_with_chunks(client, alice, course, db)
    chunks = list(db.scalars(select(ContentChunk).where(ContentChunk.course_id == cid)))
    assert build_topics_llm(db, cid, chunks, FakeLLM("not json at all")) is False
    assert build_topics_llm(db, cid, chunks, FakeLLM(json.dumps({"topics": []}))) is False
    result = rebuild_topics(db, cid, FakeLLM("not json at all"))
    assert result["method"] == "heuristic" and result["topics"] >= 1


def test_llm_provider_failure_logs_safe_reason_and_falls_back(client, alice, course, db, caplog):
    from app.services.providers.base import ProviderError

    cid = _course_with_chunks(client, alice, course, db)
    chunks = list(db.scalars(select(ContentChunk).where(ContentChunk.course_id == cid)))
    provider_error = FakeLLM(raises=ProviderError("Google language model returned HTTP 503: service unavailable"))

    assert build_topics_llm(db, cid, chunks, provider_error) is False
    assert "HTTP 503: service unavailable" in caplog.text

    result = rebuild_topics(db, cid, provider_error)
    assert result["method"] == "heuristic"


def test_llm_cannot_reference_chunks_it_wasnt_shown(client, alice, course, db):
    cid = _course_with_chunks(client, alice, course, db)
    _reset(db, cid)
    chunks = list(db.scalars(select(ContentChunk).where(ContentChunk.course_id == cid)))
    reply = json.dumps({"topics": [{"name": "Only", "chunks": [0, 99, -1, "x"]}]})
    assert build_topics_llm(db, cid, chunks, FakeLLM(reply)) is True
    assert sum(1 for c in chunks if c.topic_id is not None) == 1  # indexes 99, -1, "x" were ignored


def test_parallel_uploads_do_not_create_duplicate_topic_sets(alice, course, db):
    """Regression: files finishing at the same moment used to each build their own topics (PostgreSQL only)."""
    import pytest
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from app.main import app
    if db.bind.dialect.name != "postgresql":
        pytest.skip("needs real concurrent transactions (run with TEST_DATABASE_URL=postgresql+...)")
    docs = [samples.make_text_pdf([f"Document {i} explains heat, entropy and the Carnot cycle in detail."]) for i in range(4)]

    def go(i):
        with TestClient(app) as c:
            r = c.post(f"/api/courses/{course['id']}/documents", headers=alice, files={"file": (f"d{i}.pdf", docs[i], "application/pdf")})
            assert r.status_code == 201
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(go, range(4)))
    db.expire_all()
    cid = uuid.UUID(course["id"])
    n_topics = db.scalar(select(func.count()).select_from(Topic).where(Topic.course_id == cid))
    unassigned = db.scalar(select(func.count()).select_from(ContentChunk).where(ContentChunk.course_id == cid, ContentChunk.topic_id.is_(None)))
    # one build over 4 passages yields at most 2 clusters; separate racing builds would each add their own
    assert n_topics <= 2 and unassigned == 0
