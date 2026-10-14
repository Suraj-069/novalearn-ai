"""Assessment orchestration: plan -> generate -> verify -> de-duplicate -> store; and attempt submission."""
import random
import secrets
import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models._types import utcnow
from app.models.assessment import (Assessment, AssessmentAttempt, AssessmentQuestion, Question, QuestionSource, StudentAnswer)
from app.models.knowledge import ContentChunk, Topic
from app.models.user import User
from app.services.assessment import cloze
from app.services.assessment.dedupe import DuplicateIndex
from app.services.assessment.grade import Grade, grade_answer, grade_short_answer_with_llm
from app.services.assessment.llm_gen import make_llm_candidate
from app.services.assessment.common import Candidate, GenerationReport, Rejection, normalize
from app.services.assessment.verify import second_check, verify_candidate
from app.services.learner.mastery import latest_mastery, record_answer
from app.services.learner.recommend import generate_recommendations
from app.services.providers.base import ProviderError

TIME_GRACE_SECONDS = 15
OFFLINE_DIFFICULTY = {"mcq": ("easy",), "short_answer": ("medium", "hard")}


class AssessmentError(Exception):
    """User-presentable failure."""


def _allocate(groups: list, weights: dict, n: int, equal: bool) -> dict:
    if not groups:
        return {}
    if equal and n <= len(groups):  # diagnostic with few questions: spread across topics
        return {g: 1 for g in groups[:n]}
    total = sum(weights[g] for g in groups)
    ideal = {g: n * weights[g] / total for g in groups}
    alloc = {g: int(ideal[g]) for g in groups}
    for g in sorted(groups, key=lambda g: ideal[g] - alloc[g], reverse=True)[: n - sum(alloc.values())]:
        alloc[g] += 1
    return {g: k for g, k in alloc.items() if k > 0}


def _eligible_assessment_chunk(chunk: ContentChunk, llm) -> bool:
    return len(chunk.text) >= 40 and (not chunk.is_generated_description or (llm is not None and bool(chunk.figure_ref)))


def create_assessment(db: Session, *, user: User, course_id: uuid.UUID, mode: str, topic_ids: list[uuid.UUID], n: int, difficulty: str,
                      types: list[str], timed: bool, minutes: int | None, embedder, llm, seed: int | None = None) -> tuple[Assessment, list[Question], GenerationReport]:
    rng = random.Random(seed if seed is not None else secrets.randbits(32))
    report = GenerationReport(requested=n)

    chunks = [c for c in db.scalars(select(ContentChunk).where(ContentChunk.course_id == course_id).order_by(ContentChunk.document_id, ContentChunk.chunk_index))
              if _eligible_assessment_chunk(c, llm)]
    if not chunks:
        raise AssessmentError("This course has no indexed material to build questions from yet.")
    topics = db.scalars(select(Topic).where(Topic.course_id == course_id)).all()
    names = {t.id: t.name for t in topics}
    has_topics = bool(topics)
    vocab = cloze.build_vocab(chunks)

    selected = set(topic_ids or [])
    in_scope = [c for c in chunks if not selected or c.topic_id in selected or c.subtopic_id in selected]
    if not in_scope:
        raise AssessmentError("The selected topics have no material to build questions from.")
    by_group: dict = {}
    for c in in_scope:
        by_group.setdefault(c.topic_id, []).append(c)
    groups = list(by_group)

    mastery = latest_mastery(db, user.id)
    equal = mode == "diagnostic"
    weights = {g: 1.0 if equal else max(0.15, 1 - mastery[g].mastery) if g in mastery else 0.8 for g in groups}
    alloc = _allocate(sorted(groups, key=lambda g: (-weights[g], str(g))), weights, n, equal)

    usable = [t for t in types if t != "numerical" or llm is not None]
    if "numerical" in types and llm is None:
        report.warnings.append("Numerical questions need a language model, which isn't configured, so none were made.")
    if not usable:
        raise AssessmentError("None of the selected question types can be generated with the current setup.")
    if llm is None and difficulty != "mixed" and not any(difficulty in OFFLINE_DIFFICULTY[t] for t in usable if t in OFFLINE_DIFFICULTY):
        report.warnings.append("Without a language model, easy = multiple choice, medium = one-blank short answer, hard = two-blank short answer. "
                                f"Your selection can't produce '{difficulty}' questions, so questions were tagged by their actual format.")

    dups = DuplicateIndex(db, user.id, course_id, embedder)
    prior_chunks = {r for r in db.scalars(select(QuestionSource.chunk_id).join(Question, Question.id == QuestionSource.question_id)
                                           .join(AssessmentQuestion, AssessmentQuestion.question_id == Question.id)
                                           .join(Assessment, Assessment.id == AssessmentQuestion.assessment_id)
                                           .where(Assessment.user_id == user.id, Assessment.course_id == course_id))}
    made: list[Question] = []
    slot = [0]
    active_llm = [llm]
    consecutive_llm_failures = 0

    def next_slot() -> tuple[str, str]:
        curr_llm = active_llm[0]
        usable_now = [t for t in usable if t != "numerical" or curr_llm is not None]
        if not usable_now:
            usable_now = [t for t in OFFLINE_DIFFICULTY if t in usable] or ["mcq", "short_answer"]
        t = usable_now[slot[0] % len(usable_now)]
        slot[0] += 1
        if curr_llm is not None:
            d = difficulty if difficulty != "mixed" else ("easy", "medium", "hard")[(slot[0] - 1) % 3]
            return t, d
        opts = OFFLINE_DIFFICULTY.get(t, ("easy",))
        d = difficulty if difficulty in opts else opts[(slot[0] - 1) % len(opts)]
        return t, d

    def try_accept(cand: Candidate) -> bool:
        ok, checks, why = verify_candidate(cand, has_topics=has_topics)
        if not ok:
            report.rejected.append(Rejection("failed_verification", "; ".join(why)))
            return False
        if cand.method == "llm" and active_llm[0] is not None:
            try:
                verdict, note = second_check(active_llm[0], cand)
            except Exception:
                verdict, note = None, "model check unavailable"
        else:
            verdict, note = (None, "deterministic by construction")
        if verdict is False:
            report.rejected.append(Rejection("model_check_rejected"))
            return False
        dup, vec = dups.check(cand.text)
        if dup:
            report.rejected.append(Rejection("duplicate"))
            return False
        q = Question(course_id=course_id, topic_id=cand.topic_id, subtopic_id=cand.subtopic_id, text=cand.text, normalized_text=normalize(cand.text),
                     question_type=cand.qtype, difficulty=cand.difficulty, options=cand.options, answer_key=cand.answer_key, explanation=cand.explanation,
                     rubric=cand.rubric, verification_status="verified", generation_method=cand.method, embedding=vec,
                     verification={"checks": checks, "second_check": {"result": verdict, "note": note}})
        db.add(q)
        db.flush()
        db.add(QuestionSource(question_id=q.id, chunk_id=cand.chunk_id))
        dups.add(cand.text, vec)
        made.append(q)
        return True

    def fill(group, quota: int, per_chunk: int) -> int:
        nonlocal consecutive_llm_failures
        got = 0
        pool = by_group[group][:]
        rng.shuffle(pool)
        pool.sort(key=lambda c: c.id in prior_chunks)  # unseen material first
        used = Counter()
        for c in pool:
            if got >= quota:
                break
            while used[c.id] < per_chunk and got < quota:
                t, d = next_slot()
                cands = []
                if active_llm[0] is not None:
                    try:
                        cand = make_llm_candidate(active_llm[0], c, t, d, language=user.language)
                        cands = [cand] if cand else []
                        consecutive_llm_failures = 0
                    except ProviderError:
                        consecutive_llm_failures += 1
                        if consecutive_llm_failures >= 2:
                            active_llm[0] = None
                            msg = "Language model was slow or unavailable; switched to fast deterministic question generation."
                            if msg not in report.warnings:
                                report.warnings.append(msg)
                        cands = cloze.make_candidates(c, vocab, names, t, d, rng)
                else:
                    cands = cloze.make_candidates(c, vocab, names, t, d, rng)

                used[c.id] += 1
                if any(try_accept(x) for x in cands):
                    got += 1
        return got

    for g, quota in alloc.items():
        fill(g, quota, 1)
    for per_chunk in (1, 3):  # top up from any topic if some topics ran out of fresh material
        for g in sorted(groups, key=lambda g: -weights[g]):
            if len(made) >= n:
                break
            fill(g, n - len(made), per_chunk)

    if not made:
        raise AssessmentError("No questions could be verified from this material"
                              + (" (it may be too short, or you've already seen the questions it can produce)." if dups.history_size else " (it may be too short or too fragmentary)."))
    report.accepted = len(made)
    if len(made) < n:
        report.warnings.append(f"Only {len(made)} of {n} questions could be made and verified from the selected material"
                                + (f", partly because {sum(1 for r in report.rejected if r.reason == 'duplicate')} candidates repeated questions you've seen." if any(r.reason == "duplicate" for r in report.rejected) else "."))
    rng.shuffle(made)

    a = Assessment(user_id=user.id, course_id=course_id, mode=mode, timed=timed, time_limit_seconds=(minutes * 60 if timed and minutes else None),
                   config={"requested": n, "difficulty": difficulty, "types": types, "topic_ids": [str(t) for t in (topic_ids or [])], "seed": seed,
                           "adaptive": not equal, "generation": "llm" if any(q.generation_method == "llm" for q in made) else "cloze"})
    db.add(a)
    db.flush()
    for i, q in enumerate(made):
        db.add(AssessmentQuestion(assessment_id=a.id, question_id=q.id, position=i))
    db.flush()
    return a, made, report


# ---------------------------------------------------------------- attempts

def assessment_questions(db: Session, assessment_id) -> list[Question]:
    return list(db.scalars(select(Question).join(AssessmentQuestion, AssessmentQuestion.question_id == Question.id)
                           .where(AssessmentQuestion.assessment_id == assessment_id).order_by(AssessmentQuestion.position)))


def infer_misconception(q: Question, answer: dict | None, grade: Grade) -> str | None:
    """A hint about *why* an answer may be wrong. Always phrased as inferred, never as fact."""
    if not grade.answered or grade.is_correct:
        return None
    if q.question_type == "mcq":
        chosen = next((o for o in (q.options or []) if o["id"] == answer.get("value")), None)
        right = next((o for o in q.options if o["id"] == q.answer_key["correct"]), None)
        if chosen and chosen.get("from_topic"):
            return f"Inferred: you chose \u201c{chosen['text']}\u201d, a term from {chosen['from_topic']}; you may be mixing it up with \u201c{right['text']}\u201d."
        if chosen:
            return f"Inferred: \u201c{chosen['text']}\u201d is a plausible-sounding option that the source does not support."
    if q.question_type == "short_answer" and grade.feedback.get("missing"):
        return "Inferred: your answer is missing: " + ", ".join(grade.feedback["missing"]) + "."
    if q.question_type == "numerical":
        got, want = grade.feedback.get("submitted"), grade.feedback.get("expected")
        if got and want and any(abs(got - want * f) <= 0.01 * abs(want * f) for f in (100, 0.01, 1000, 0.001)):
            return "Inferred: your answer is off by a power of ten, which often means a unit or percentage slip."
    return None


def start_attempt(db: Session, user: User, assessment: Assessment) -> AssessmentAttempt:
    existing = db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.assessment_id == assessment.id, AssessmentAttempt.user_id == user.id)
                          .order_by(AssessmentAttempt.started_at.desc())).first()
    if existing is not None:
        if existing.submitted_at is not None:
            raise AssessmentError("You've already completed this assessment. Create a new one: questions aren't repeated.")
        return existing
    att = AssessmentAttempt(assessment_id=assessment.id, user_id=user.id, meta={})
    db.add(att)
    db.flush()
    return att


def submit_attempt(db: Session, user: User, attempt: AssessmentAttempt, assessment: Assessment,
                   answers: dict[uuid.UUID, object], *, grading_llm=None) -> None:
    if attempt.submitted_at is not None:
        raise AssessmentError("This attempt was already submitted.")
    qs = assessment_questions(db, assessment.id)
    unknown = set(answers) - {q.id for q in qs}
    if unknown:
        raise AssessmentError("Your answers include a question that isn't part of this assessment.")
    now = utcnow()
    started = attempt.started_at if attempt.started_at.tzinfo else attempt.started_at.replace(tzinfo=timezone.utc)
    elapsed = (now - started).total_seconds()
    overtime = max(0.0, elapsed - assessment.time_limit_seconds) if assessment.timed and assessment.time_limit_seconds else 0.0
    total = 0.0
    for q in qs:
        ans = {"value": answers.get(q.id)}
        if q.question_type == "short_answer" and grading_llm is not None:
            source_text = db.scalar(select(ContentChunk.text).join(QuestionSource, QuestionSource.chunk_id == ContentChunk.id)
                                    .where(QuestionSource.question_id == q.id, ContentChunk.course_id == q.course_id).limit(1))
            g = grade_short_answer_with_llm(q, ans, source_text or "", grading_llm)
        else:
            g = grade_answer(q, ans)
        total += g.score
        fb = dict(g.feedback)
        hint = infer_misconception(q, ans, g)
        if hint:
            fb["misconception"] = hint
        db.add(StudentAnswer(attempt_id=attempt.id, question_id=q.id, answer=ans, is_correct=g.is_correct if g.answered else None,
                             score=g.score if g.answered else None, feedback=fb))
        if g.answered:  # unanswered questions give no evidence either way
            chunk_ids = [str(r) for r in db.scalars(select(QuestionSource.chunk_id).where(QuestionSource.question_id == q.id))]
            record_answer(db, user_id=user.id, question=q, score=g.score, attempt=attempt, chunk_ids=chunk_ids)
    attempt.score, attempt.max_score, attempt.submitted_at = round(total, 4), float(len(qs)), now
    attempt.meta = {"overtime_seconds": round(overtime, 1), "elapsed_seconds": round(elapsed, 1), "answered": len([a for a in answers.values() if a not in (None, "")])}
    db.flush()
    generate_recommendations(db, user.id, assessment.course_id)
