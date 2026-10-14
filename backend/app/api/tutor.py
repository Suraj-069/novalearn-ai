import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_course
from app.core.config import get_settings
from app.database.session import get_db
from app.models.course import Document
from app.models.knowledge import ContentChunk, Topic
from app.services.learner.mastery import record_conversation_signal
from app.models.tutoring import Conversation, ConversationMessage
from app.models.user import User
from app.schemas.knowledge import ChatIn, ChatOut, ConversationOut, MessageOut
from app.core.binaries import find_system_binary
from app.services.ingestion.ocr import ocr_available
from app.services.providers.base import ProviderError, ProviderUnavailable
from app.services.providers.embeddings import get_embedding_provider
from app.services.providers.llm import get_llm
from app.services.tutoring.service import answer_question

router = APIRouter(prefix="/api", tags=["tutor"])


@router.get("/system/capabilities")
def capabilities(user: User = Depends(current_user)):
    """What this installation can really do. The UI uses this to explain limitations honestly."""
    s = get_settings()
    try:
        emb = get_embedding_provider()
        emb_info = {"provider": emb.name, "semantic": emb.semantic}
    except ProviderUnavailable as e:
        emb_info = {"provider": None, "semantic": False, "error": str(e)}
    try:
        llm = get_llm()
        llm_info = {"configured": llm is not None, "provider": llm.name if llm else None}
    except ProviderUnavailable as e:
        llm_info = {"configured": False, "provider": None, "error": str(e)}
    return {
        "llm": llm_info, "embeddings": emb_info,
        "speech_to_text": {"configured": s.stt_provider not in ("none", ""), "provider": s.stt_provider},
        "ocr": {"available": ocr_available()},
        "ffmpeg": {"available": find_system_binary("ffmpeg") is not None},
        "vision": {"enabled": s.vision_enabled and llm_info["configured"]},
    }


def _hydrate(db: Session, msgs: list[ConversationMessage]) -> list[MessageOut]:
    """Re-validate stored citations: a source deleted since the answer was given is flagged, never shown as live."""
    ids = {uuid.UUID(c["chunk_id"]) for m in msgs for c in (m.citations or [])}
    existing = set(db.scalars(select(ContentChunk.id).where(ContentChunk.id.in_(ids)))) if ids else set()
    out = []
    for m in msgs:
        cites = []
        for c in m.citations or []:
            ok = uuid.UUID(c["chunk_id"]) in existing
            cites.append({**c, "available": ok} if ok else {"n": c["n"], "available": False, "filename": c.get("filename"),
                                                              "excerpt": "", "chunk_id": c["chunk_id"], "document_id": c.get("document_id")})
        out.append(MessageOut(id=m.id, role=m.role, content=m.content, citations=cites, grounded=m.grounded,
                              mode=m.mode, created_at=m.created_at))
    return out


def _owned_conversation(cid: uuid.UUID, user: User, db: Session) -> Conversation:
    c = db.get(Conversation, cid)
    if c is None or c.user_id != user.id:
        raise HTTPException(404, "Conversation not found.")
    return c


@router.post("/courses/{course_id}/chat", response_model=ChatOut)
def chat(course_id: uuid.UUID, body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    course = owned_course(course_id, user, db)
    indexed = db.scalar(select(ContentChunk.id).where(ContentChunk.course_id == course.id).limit(1))
    if indexed is None:
        raise HTTPException(409, "This course has no indexed material yet. Upload files and wait for them to finish processing.")
    if body.topic_id:
        t = db.get(Topic, body.topic_id)
        if t is None or t.course_id != course.id:
            raise HTTPException(400, "That topic isn't in this course.")
    if body.conversation_id:
        conv = _owned_conversation(body.conversation_id, user, db)
        if conv.course_id != course.id:
            raise HTTPException(404, "Conversation not found.")
    else:
        conv = Conversation(user_id=user.id, course_id=course.id, topic_id=body.topic_id, title=body.question.strip()[:60])
        db.add(conv); db.flush()

    prior = [m.content for m in db.scalars(select(ConversationMessage).where(
        ConversationMessage.conversation_id == conv.id, ConversationMessage.role == "user").order_by(ConversationMessage.created_at))]
    try:
        llm = get_llm()
        result = answer_question(db, user=user, course_id=course.id, question=body.question.strip(), embedder=get_embedding_provider(),
                                 llm=llm, history=prior, topic_id=body.topic_id, mode=body.mode, allow_general=body.allow_general)
    except ProviderUnavailable as e:
        raise HTTPException(503, f"AI provider not configured correctly: {e}")
    except ProviderError as e:
        raise HTTPException(502, str(e))

    um = ConversationMessage(conversation_id=conv.id, role="user", content=body.question.strip(), citations=[])
    am = ConversationMessage(conversation_id=conv.id, role="assistant", content=result.answer,
                             citations=result.citations, grounded=result.grounded, mode=result.mode)
    db.add_all([um, am])
    if result.grounded:
        signal_topic_id = body.topic_id or conv.topic_id
        if signal_topic_id is None:
            cited_ids = [uuid.UUID(c["chunk_id"]) for c in result.citations if c.get("chunk_id")]
            cited_topic_id = db.scalar(select(ContentChunk.topic_id).where(
                ContentChunk.course_id == course.id, ContentChunk.id.in_(cited_ids), ContentChunk.topic_id.is_not(None)
            ).limit(1)) if cited_ids else None
            signal_topic_id = cited_topic_id
        if signal_topic_id is not None:
            record_conversation_signal(db, user_id=user.id, topic_id=signal_topic_id, conversation_id=conv.id,
                                      question=body.question.strip(), prior_user_turns=len(prior))
    db.commit()
    out = _hydrate(db, [um, am])
    return ChatOut(conversation_id=conv.id, user_message=out[0], assistant_message=out[1])


@router.get("/courses/{course_id}/conversations", response_model=list[ConversationOut])
def conversations(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    return db.scalars(select(Conversation).where(Conversation.course_id == course_id, Conversation.user_id == user.id)
                      .order_by(Conversation.created_at.desc()).limit(50)).all()


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def messages(conversation_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conv = _owned_conversation(conversation_id, user, db)
    msgs = db.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conv.id)
                      .order_by(ConversationMessage.created_at)).all()
    return _hydrate(db, list(msgs))


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_owned_conversation(conversation_id, user, db)); db.commit()


@router.get("/courses/{course_id}/suggestions")
def suggestions(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Suggested questions built from this course's real topics and files."""
    owned_course(course_id, user, db)
    topics = db.scalars(select(Topic).where(Topic.course_id == course_id, Topic.parent_id.is_(None)).order_by(Topic.created_at).limit(4)).all()
    out = [f"Explain {t.name}" for t in topics]
    if len(topics) >= 2:
        out.append(f"What is the difference between {topics[0].name} and {topics[1].name}?")
    if topics:
        out.append(f"Give me a revision summary of {topics[0].name}")
    return out[:5]
