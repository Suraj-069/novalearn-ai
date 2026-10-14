import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_course
from app.database.session import get_db
from app.models.course import Document
from app.models.knowledge import ContentChunk, Topic, TopicPrerequisite
from app.models.user import User
from app.schemas.knowledge import ChunkPatch, PrereqIn, TopicIn, TopicOut, TopicPatch
from app.services.knowledge.topics import _has_cycle, rebuild_topics
from app.services.learner.mastery import latest_mastery
from app.services.providers.base import ProviderUnavailable
from app.services.providers.llm import get_llm
from app.services.retrieval.citations import citation_for

router = APIRouter(prefix="/api", tags=["knowledge"])


def owned_topic(topic_id: uuid.UUID, user: User, db: Session) -> Topic:
    t = db.get(Topic, topic_id)
    if t is None:
        raise HTTPException(404, "Topic not found.")
    owned_course(t.course_id, user, db)  # 404 if the course isn't theirs
    return t


def owned_chunk(chunk_id: uuid.UUID, user: User, db: Session) -> ContentChunk:
    c = db.get(ContentChunk, chunk_id)
    if c is None:
        raise HTTPException(404, "Source not found.")
    owned_course(c.course_id, user, db)
    return c


@router.get("/courses/{course_id}/topics", response_model=list[TopicOut])
def list_topics(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    topics = db.scalars(select(Topic).where(Topic.course_id == course_id).order_by(Topic.created_at, Topic.name)).all()
    names = {t.id: t for t in topics}
    docs = {d.id: d.original_filename for d in db.scalars(select(Document).where(Document.course_id == course_id))}
    rows = db.execute(select(ContentChunk.topic_id, ContentChunk.subtopic_id, ContentChunk.source_type, ContentChunk.document_id, func.count())
                      .where(ContentChunk.course_id == course_id).group_by(ContentChunk.topic_id, ContentChunk.subtopic_id, ContentChunk.source_type, ContentChunk.document_id)).all()
    stats: dict[uuid.UUID, dict] = {t.id: {"n": 0, "src": {}, "docs": {}} for t in topics}
    for tid, sid, stype, did, n in rows:
        for key in {tid, sid}:  # a chunk in a subtopic also counts toward its parent topic
            if key in stats:
                s = stats[key]; s["n"] += n
                s["src"][stype] = s["src"].get(stype, 0) + n
                s["docs"][did] = s["docs"].get(did, 0) + n
    mastery = latest_mastery(db, user.id, list(names) or None) if names else {}
    prereqs: dict[uuid.UUID, list[dict]] = {}
    for p in db.scalars(select(TopicPrerequisite).where(TopicPrerequisite.topic_id.in_(list(names) or [uuid.uuid4()]))):
        if p.prerequisite_id in names:
            prereqs.setdefault(p.topic_id, []).append({"id": str(p.prerequisite_id), "name": names[p.prerequisite_id].name, "origin": p.origin})
    return [
        TopicOut(id=t.id, parent_id=t.parent_id, name=t.name, description=t.description, origin=t.origin,
                 chunk_count=stats[t.id]["n"], source_counts=stats[t.id]["src"],
                 documents=[{"id": str(d), "filename": docs.get(d, "?"), "chunks": n} for d, n in stats[t.id]["docs"].items()],
                 prerequisites=prereqs.get(t.id, []),
                 mastery=mastery[t.id].mastery if t.id in mastery else None, mastery_evidence=mastery[t.id].evidence if t.id in mastery else 0)
        for t in topics
    ]


@router.post("/courses/{course_id}/topics", response_model=TopicOut, status_code=201)
def create_topic(course_id: uuid.UUID, body: TopicIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    if body.parent_id:
        parent = db.get(Topic, body.parent_id)
        if parent is None or parent.course_id != course_id:
            raise HTTPException(400, "Parent topic isn't in this course.")
    t = Topic(course_id=course_id, name=body.name.strip(), description=body.description, parent_id=body.parent_id, origin="user")
    db.add(t); db.commit()
    return TopicOut(id=t.id, parent_id=t.parent_id, name=t.name, description=t.description, origin="user",
                    chunk_count=0, source_counts={}, documents=[], prerequisites=[])


@router.patch("/topics/{topic_id}", response_model=dict)
def patch_topic(topic_id: uuid.UUID, body: TopicPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned_topic(topic_id, user, db)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        t.name = data["name"].strip() or t.name
    if "description" in data and data["description"] is not None:
        t.description = data["description"]
    if data.get("clear_parent"):
        t.parent_id = None
    elif data.get("parent_id"):
        p = db.get(Topic, data["parent_id"])
        if p is None or p.course_id != t.course_id or p.id == t.id or p.parent_id is not None:
            raise HTTPException(400, "Invalid parent topic.")
        t.parent_id = p.id
    if t.origin == "auto":
        # Editing an automatic topic makes it yours: it, and the passages currently in it, are kept on rebuild.
        t.origin = "user"
        for c in db.scalars(select(ContentChunk).where(ContentChunk.course_id == t.course_id,
                                                       (ContentChunk.topic_id == t.id) | (ContentChunk.subtopic_id == t.id))):
            c.topic_locked = True
    db.commit()
    return {"ok": True}


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned_topic(topic_id, user, db)
    db.delete(t); db.commit()


@router.post("/topics/{topic_id}/prerequisites", status_code=201)
def add_prerequisite(topic_id: uuid.UUID, body: PrereqIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned_topic(topic_id, user, db)
    other = owned_topic(body.prerequisite_id, user, db)
    if other.course_id != t.course_id or other.id == t.id:
        raise HTTPException(400, "Invalid prerequisite.")
    edges = [(str(a), str(b)) for a, b in db.execute(select(TopicPrerequisite.topic_id, TopicPrerequisite.prerequisite_id)
             .join(Topic, Topic.id == TopicPrerequisite.topic_id).where(Topic.course_id == t.course_id))]
    edges.append((str(t.id), str(other.id)))
    if _has_cycle(edges):
        raise HTTPException(400, "That would create a circular prerequisite.")
    if db.get(TopicPrerequisite, (t.id, other.id)) is None:
        db.add(TopicPrerequisite(topic_id=t.id, prerequisite_id=other.id, origin="user")); db.commit()
    return {"ok": True}


@router.delete("/topics/{topic_id}/prerequisites/{prereq_id}", status_code=204)
def remove_prerequisite(topic_id: uuid.UUID, prereq_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_topic(topic_id, user, db)
    p = db.get(TopicPrerequisite, (topic_id, prereq_id))
    if p:
        db.delete(p); db.commit()


@router.get("/topics/{topic_id}/sources")
def topic_sources(topic_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = owned_topic(topic_id, user, db)
    q = select(ContentChunk, Document).join(Document, Document.id == ContentChunk.document_id).where(
        ContentChunk.course_id == t.course_id, (ContentChunk.topic_id == t.id) | (ContentChunk.subtopic_id == t.id)
    ).order_by(ContentChunk.document_id, ContentChunk.chunk_index).limit(40)
    return [citation_for(i + 1, c, d) for i, (c, d) in enumerate(db.execute(q).all())]


@router.post("/courses/{course_id}/topics/rebuild")
def rebuild(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    try:
        llm = get_llm()
    except ProviderUnavailable:
        llm = None
    result = rebuild_topics(db, course_id, llm)
    db.commit()
    return result


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = owned_chunk(chunk_id, user, db)
    c_doc = db.get(Document, c.document_id)
    full = citation_for(0, c, c_doc)
    full["text"] = c.text
    full["topic_id"] = str(c.topic_id) if c.topic_id else None
    return full


@router.patch("/chunks/{chunk_id}")
def move_chunk(chunk_id: uuid.UUID, body: ChunkPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Correct a wrong topic assignment. The chunk is then locked so a rebuild won't undo the correction."""
    c = owned_chunk(chunk_id, user, db)
    if body.topic_id is not None:
        t = db.get(Topic, body.topic_id)
        if t is None or t.course_id != c.course_id:
            raise HTTPException(400, "That topic isn't in this course.")
        c.topic_id, c.subtopic_id = (t.parent_id or t.id), (t.id if t.parent_id else None)
        c.topic_locked = True
    else:
        c.topic_id = c.subtopic_id = None
        c.topic_locked = True
    db.commit()
    return {"ok": True}
