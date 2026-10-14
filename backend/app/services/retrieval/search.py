"""Hybrid retrieval: vector similarity + keyword ranking, fused with Reciprocal Rank Fusion.

Always scoped to a single course (the caller has already authorised access to it).
PostgreSQL uses pgvector and full-text search; SQLite (tests) uses an equivalent Python fallback.
"""
import math
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.knowledge import ContentChunk, Topic
from app.services.providers.text import tokens

CANDIDATES = 30
RRF_K = 60


@dataclass
class Hit:
    chunk: ContentChunk
    vector_score: float | None
    keyword_rank: int | None
    fused: float
    lexical_support: float  # share of the question's content words found in this chunk (0..1)


def topic_subtree_ids(db: Session, course_id: uuid.UUID, topic_id: uuid.UUID) -> list[uuid.UUID]:
    topics = db.execute(select(Topic.id, Topic.parent_id).where(Topic.course_id == course_id)).all()
    ids, frontier = {topic_id}, [topic_id]
    while frontier:
        cur = frontier.pop()
        for tid, parent in topics:
            if parent == cur and tid not in ids:
                ids.add(tid); frontier.append(tid)
    return list(ids)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _scope(course_id, topic_ids):
    q = select(ContentChunk).where(ContentChunk.course_id == course_id, ContentChunk.embedding.is_not(None))
    if topic_ids:
        q = q.where(or_(ContentChunk.topic_id.in_(topic_ids), ContentChunk.subtopic_id.in_(topic_ids)))
    return q


def _vector_candidates(db: Session, course_id, qvec, topic_ids) -> list[tuple[ContentChunk, float]]:
    base = _scope(course_id, topic_ids)
    if db.bind.dialect.name == "postgresql":
        dist = ContentChunk.embedding.cosine_distance(qvec)
        rows = db.execute(base.add_columns(dist.label("d")).order_by(dist).limit(CANDIDATES)).all()
        return [(r[0], 1.0 - float(r[1])) for r in rows]
    chunks = db.scalars(base).all()
    scored = [(c, cosine(qvec, c.embedding)) for c in chunks]
    return sorted(scored, key=lambda x: -x[1])[:CANDIDATES]


def _keyword_candidates(db: Session, course_id, query: str, topic_ids) -> list[ContentChunk]:
    q_terms = sorted(set(tokens(query)))
    if not q_terms:
        return []
    base = _scope(course_id, topic_ids)
    if db.bind.dialect.name == "postgresql":
        safe = [re.sub(r"[^a-z0-9]", "", t) for t in re.findall(r"[a-z0-9]+", query.lower())]
        safe = [t for t in dict.fromkeys(safe) if t and t not in {"the", "a", "an", "of", "and", "or", "is", "to", "in"}]
        if not safe:
            return []
        tsq = func.to_tsquery("english", " | ".join(safe))
        tsv = func.to_tsvector("english", ContentChunk.text)
        rank = func.ts_rank_cd(tsv, tsq)
        return list(db.scalars(base.where(tsv.op("@@")(tsq)).order_by(rank.desc()).limit(CANDIDATES)))
    # SQLite fallback: BM25-style scoring in Python over the course's chunks
    chunks = db.scalars(base).all()
    docs = [tokens(c.text) for c in chunks]
    n, avg = len(docs), (sum(len(d) for d in docs) / len(docs) if docs else 1)
    df = {t: sum(1 for d in docs if t in d) for t in q_terms}
    scored = []
    for c, d in zip(chunks, docs):
        s = 0.0
        for t in q_terms:
            tf = d.count(t)
            if tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(d) / avg))
        if s > 0:
            scored.append((c, s))
    return [c for c, _ in sorted(scored, key=lambda x: -x[1])[:CANDIDATES]]


def lexical_support(query: str, text: str) -> float:
    q = set(tokens(query))
    if not q:
        return 0.0
    return len(q & set(tokens(text))) / len(q)


def hybrid_search(db: Session, course_id: uuid.UUID, query: str, embedder, *, k: int | None = None,
                  topic_ids: list[uuid.UUID] | None = None) -> list[Hit]:
    k = k or get_settings().retrieval_top_k
    qvec = embedder.embed([query])[0]
    vec = _vector_candidates(db, course_id, qvec, topic_ids)
    kw = _keyword_candidates(db, course_id, query, topic_ids)

    fused: dict[uuid.UUID, float] = {}
    chunks: dict[uuid.UUID, ContentChunk] = {}
    vscore: dict[uuid.UUID, float] = {}
    krank: dict[uuid.UUID, int] = {}
    for rank, (c, sc) in enumerate(vec, start=1):
        chunks[c.id] = c; vscore[c.id] = sc
        fused[c.id] = fused.get(c.id, 0.0) + 1.0 / (RRF_K + rank)
    for rank, c in enumerate(kw, start=1):
        chunks[c.id] = c; krank[c.id] = rank
        fused[c.id] = fused.get(c.id, 0.0) + 1.0 / (RRF_K + rank)

    hits = [Hit(chunks[i], vscore.get(i), krank.get(i), f, lexical_support(query, chunks[i].text)) for i, f in fused.items()]
    hits.sort(key=lambda h: -h.fused)
    return hits[:k]


def evidence_supported(query: str, hits: list[Hit], embedder) -> bool:
    """Is there enough evidence in the course material to answer? Conservative by design.

    Lexical embeddings can't judge meaning, so they require that the question's content words
    actually appear in a retrieved passage. Semantic embeddings use cosine similarity.
    """
    if not hits or not tokens(query):
        return False
    s = get_settings()
    if embedder.semantic:
        best = max((h.vector_score or 0.0) for h in hits)
        return best >= s.min_semantic_score
    return max(h.lexical_support for h in hits) >= s.min_lexical_support
