"""Live provider and LLM learning-feature smoke checks.

Run from backend/: python scripts/check_providers.py [--audio path-to-short-speech-file]
Calls configured providers for real; synthetic feature data lives in a temporary SQLite database.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.database.session import Base  # noqa: E402
from app.models.course import Course, Document  # noqa: E402
from app.models.knowledge import ContentChunk, Topic, TopicPrerequisite  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.assessment.service import create_assessment  # noqa: E402
from app.services.knowledge.topics import build_topics_llm  # noqa: E402
from app.services.providers.base import ProviderUnavailable  # noqa: E402
from app.services.providers.embeddings import get_embedding_provider  # noqa: E402
from app.services.providers.llm import get_llm  # noqa: E402
from app.services.providers.stt import get_stt  # noqa: E402


def _run(label: str, check) -> bool:
    started = time.perf_counter()
    try:
        detail = check()
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        print(f"[FAIL] {label}: {type(exc).__name__}: {exc} ({elapsed:.0f} ms)")
        return False
    elapsed = (time.perf_counter() - started) * 1000
    print(f"[PASS] {label}: {detail} ({elapsed:.0f} ms)")
    return True


def _temporary_course():
    """Create realistic smoke-test rows in memory; no project database is written."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)

    user = User(email="provider-smoke@example.invalid", name="Provider smoke", password_hash="unused")
    db.add(user)
    db.flush()
    course = Course(owner_id=user.id, title="Provider smoke course")
    db.add(course)
    db.flush()
    document = Document(
        course_id=course.id,
        original_filename="provider-smoke.txt",
        stored_path="provider-smoke.txt",
        source_type="pdf",
        mime_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
    )
    db.add(document)
    db.flush()

    excerpts = [
        "Algebra is a foundation for calculus. Students should solve linear equations and rearrange expressions before studying derivatives.",
        "Calculus builds on algebra. A derivative is the limit of a difference quotient and describes the instantaneous rate of change.",
        "In mechanics, work is force multiplied by displacement along the force direction. The formula is W = F * d, where W is work in joules, F is force in newtons, and d is distance in metres. Kinematics also uses calculus to relate position and velocity.",
    ]
    chunks = [
        ContentChunk(course_id=course.id, document_id=document.id, chunk_index=i, source_type="pdf", text=body)
        for i, body in enumerate(excerpts)
    ]
    db.add_all(chunks)
    db.commit()
    return engine, db, user, course, chunks


def _topic_check(db: Session, course: Course, chunks: list[ContentChunk], llm) -> str:
    if not build_topics_llm(db, course.id, chunks, llm):
        raise RuntimeError("LLM topic extraction rejected its response")
    db.flush()
    topics = db.scalars(select(Topic).where(Topic.course_id == course.id)).all()
    edges = db.scalars(
        select(TopicPrerequisite)
        .join(Topic, Topic.id == TopicPrerequisite.topic_id)
        .where(Topic.course_id == course.id)
    ).all()
    if not edges:
        raise RuntimeError(f"topic extraction produced {len(topics)} topics but no prerequisite links")
    return f"{len(topics)} topics, {len(edges)} prerequisite link(s)"


def _numerical_check(db: Session, user: User, course: Course, chunks: list[ContentChunk], embedder, llm) -> str:
    formula_chunk = chunks[2]
    topics = db.scalars(select(Topic).where(Topic.course_id == course.id, Topic.parent_id.is_(None))).all()
    if not topics:
        raise RuntimeError("topic extraction created no topics for the numerical question smoke check")
    if formula_chunk.topic_id is None:
        # The synthetic formula excerpt can be left unassigned by a valid topic partition.
        formula_chunk.topic_id = topics[0].id
        db.flush()

    assessment, questions, report = create_assessment(
        db,
        user=user,
        course_id=course.id,
        mode="quiz",
        topic_ids=[formula_chunk.topic_id],
        n=1,
        difficulty="medium",
        types=["numerical"],
        timed=False,
        minutes=None,
        embedder=embedder,
        llm=llm,
        seed=2026,
    )
    numerical = [q for q in questions if q.question_type == "numerical"]
    if not numerical:
        raise RuntimeError(f"no numerical question accepted; rejected {len(report.rejected)} candidate(s)")
    question = numerical[0]
    checks = (question.verification or {}).get("checks", {})
    if question.verification_status != "verified" or not checks or not all(checks.values()):
        raise RuntimeError("the generated numerical question did not pass every recorded deterministic check")
    db.commit()
    return f"1 numerical question generated and passed {len(checks)} recorded checks"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, help="short speech file to submit when STT_PROVIDER is configured")
    parser.add_argument("--model", type=str, default=None, help="override the configured LLM model for the smoke check")
    args = parser.parse_args()
    settings = get_settings()
    results: list[bool] = []

    llm = None
    def check_llm() -> str:
        nonlocal llm
        llm = get_llm(model=args.model)
        if llm is None:
            raise ProviderUnavailable("LLM_PROVIDER=none; configure a real LLM provider and model")
        answer = llm.complete(
            "Reply with a short plain-text confirmation.",
            "Reply with exactly: NOVA provider check passed.",
            max_tokens=40,
        )
        if not answer.strip():
            raise RuntimeError("provider returned an empty completion")
        return f"{llm.name}, non-empty completion"

    results.append(_run("LLM", check_llm))

    embedder = None
    def check_embedding() -> str:
        nonlocal embedder
        embedder = get_embedding_provider()
        if not getattr(embedder, "semantic", False):
            raise ProviderUnavailable("EMBEDDING_PROVIDER is local-hash; configure a real semantic embedding model")
        vectors = embedder.embed(["NOVA Learn AI provider connectivity check."])
        if len(vectors) != 1 or len(vectors[0]) != settings.embedding_dim:
            got = len(vectors[0]) if vectors else 0
            raise RuntimeError(f"model returned {got} dimensions; EMBEDDING_DIM={settings.embedding_dim}")
        return f"{embedder.name}, {len(vectors[0])} dimensions"

    results.append(_run("Embeddings", check_embedding))

    if settings.stt_provider in ("none", ""):
        print("[SKIP] STT: STT_PROVIDER is not configured")
    elif args.audio is None:
        results.append(_run("STT", lambda: (_ for _ in ()).throw(
            ValueError("STT is configured; pass --audio PATH to make a real transcription request")
        )))
    elif not args.audio.is_file():
        results.append(_run("STT", lambda: (_ for _ in ()).throw(FileNotFoundError(args.audio))))
    else:
        def check_stt() -> str:
            provider = get_stt()
            segments = provider.transcribe(str(args.audio))
            if not segments:
                raise RuntimeError("provider returned no timestamped speech segments")
            return f"{provider.name}, {len(segments)} timestamped segment(s)"
        results.append(_run("STT", check_stt))

    if llm is not None and embedder is not None and results[0] and results[1]:
        engine = db = None
        try:
            engine, db, user, course, chunks = _temporary_course()
            results.append(_run("LLM topic prerequisites", lambda: _topic_check(db, course, chunks, llm)))
            results.append(_run("LLM numerical generation + verification",
                                lambda: _numerical_check(db, user, course, chunks, embedder, llm)))
        finally:
            if db is not None:
                db.close()
            if engine is not None:
                engine.dispose()
    else:
        print("[SKIP] LLM feature checks: configure and pass the real LLM and embedding checks first")

    failed = sum(not result for result in results)
    print(f"\nProvider smoke checks: {len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
