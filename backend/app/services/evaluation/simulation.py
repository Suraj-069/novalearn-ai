"""Seeded adaptive-vs-random simulation using verified questions and the production grader/BKT."""
from __future__ import annotations

import random
import uuid

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.services.assessment.grade import grade_answer
from app.services.learner import bkt


PROFILES = (
    {"name": "weak", "skill": 0.28, "slip": 0.24, "guess": 0.20, "learning": 0.13, "forgetting": 0.02},
    {"name": "average", "skill": 0.55, "slip": 0.16, "guess": 0.18, "learning": 0.09, "forgetting": 0.01},
    {"name": "strong", "skill": 0.82, "slip": 0.09, "guess": 0.16, "learning": 0.05, "forgetting": 0.005},
    {"name": "forgetful", "skill": 0.66, "slip": 0.21, "guess": 0.20, "learning": 0.04, "forgetting": 0.08},
)


def _answer_for(question, correct: bool, rng: random.Random):
    if question.question_type == "mcq":
        right = question.answer_key["correct"]
        if correct:
            return right
        wrong = [option["id"] for option in question.options or [] if option["id"] != right]
        return rng.choice(wrong) if wrong else "simulated-wrong-option"
    if question.question_type == "numerical":
        expected = float(question.answer_key["value"])
        return str(expected if correct else expected + max(1000.0, abs(expected) + 1.0))
    accepted = (question.answer_key or {}).get("answers", [])
    return ", ".join(accepted) if correct and accepted else (accepted[0] if correct and accepted else "unrelated response")


def simulate_personalization(questions, topic_names: dict, *, sessions: int, questions_per_session: int,
                             runs: int = 5, seed: int = 17, profiles: tuple[dict, ...] = PROFILES) -> dict:
    """Compare weak-topic adaptive selection with uniform topic selection over repeated seeded runs.

    Hidden learner parameters and state are generated independently from the app's fixed BKT constants.
    Scores pass through the production deterministic grader and app BKT update. This is synthetic
    behavior only; it does not establish real learning gains.
    """
    questions = [q for q in questions if q.topic_id in topic_names and q.verification_status == "verified"]
    by_topic: dict = {}
    for question in questions:
        by_topic.setdefault(question.topic_id, []).append(question)
    if not by_topic:
        return {"available": False, "reason": "No verified topic-tagged questions are available.", "runs": []}

    detail_runs = []
    for profile_index, profile in enumerate(profiles):
        for run_index in range(runs):
            initial_rng = random.Random(seed + profile_index * 100_003 + run_index * 997)
            initial_truth = {tid: min(0.98, max(0.02, profile["skill"] + initial_rng.uniform(-0.06, 0.06))) for tid in by_topic}
            for arm_index, arm in enumerate(("random", "adaptive")):
                rng = random.Random(seed + profile_index * 1_000_003 + run_index * 10_007 + arm_index * 101)
                truth = dict(initial_truth)
                estimates = {tid: bkt.P_INIT for tid in by_topic}
                seen: set = set()
                topic_seen: set = set()
                covered_topics: set = set()
                selected_weak = 0
                total = repeats = 0
                session_rows = []
                for session in range(sessions):
                    # Apply a hidden forgetting curve only to topics not practiced in the prior session.
                    if session:
                        for tid in by_topic.keys() - topic_seen:
                            truth[tid] *= 1.0 - profile["forgetting"]
                    topic_seen = set()
                    for _ in range(questions_per_session):
                        topic_ids = list(by_topic)
                        if arm == "random":
                            topic_id = rng.choice(topic_ids)
                        else:
                            weights = [max(0.02, 1.0 - estimates[tid]) for tid in topic_ids]
                            topic_id = rng.choices(topic_ids, weights=weights, k=1)[0]
                        pool = by_topic[topic_id]
                        fresh = [q for q in pool if q.id not in seen]
                        question = rng.choice(fresh or pool)
                        repeats += int(question.id in seen)
                        seen.add(question.id)
                        topic_seen.add(topic_id)
                        covered_topics.add(topic_id)
                        total += 1
                        selected_weak += int(truth[topic_id] <= sum(truth.values()) / len(truth))

                        # A separate synthetic response model: P(correct)=mastery*(1-slip)+(1-mastery)*guess.
                        p_correct = truth[topic_id] * (1.0 - profile["slip"]) + (1.0 - truth[topic_id]) * profile["guess"]
                        intended_correct = rng.random() < p_correct
                        grade = grade_answer(question, {"value": _answer_for(question, intended_correct, rng)})
                        estimates[topic_id], _ = bkt.update(estimates[topic_id], grade.score,
                                                            question.question_type, question.difficulty)
                        # Latent truth has its own learning rate, independent of BKT's P_LEARN.
                        truth[topic_id] = min(0.98, truth[topic_id] + (1.0 - truth[topic_id]) * profile["learning"])

                    mean_truth = sum(truth.values()) / len(truth)
                    mean_estimate = sum(estimates.values()) / len(estimates)
                    session_rows.append({"session": session + 1, "true_mastery": mean_truth,
                                         "estimated_mastery": mean_estimate,
                                         "absolute_estimate_error": abs(mean_truth - mean_estimate),
                                         "topics_covered": len(topic_seen), "topic_coverage": len(topic_seen) / len(by_topic),
                                         "repeated_presentations": repeats, "presentations": total})
                detail_runs.append({
                    "profile": profile["name"], "run": run_index + 1, "arm": arm,
                    "initial_true_mastery": sum(initial_truth.values()) / len(initial_truth),
                    "final_true_mastery": sum(truth.values()) / len(truth),
                    "true_mastery_gain": sum(truth.values()) / len(truth) - sum(initial_truth.values()) / len(initial_truth),
                    "final_estimate_error": abs(sum(truth.values()) / len(truth) - sum(estimates.values()) / len(estimates)),
                    "question_repetition_rate": repeats / total if total else 0.0,
                    "weak_topic_selection_rate": selected_weak / total if total else 0.0,
                    "topic_coverage": len(covered_topics) / len(by_topic), "sessions": session_rows,
                })

    arms = {}
    for arm in ("random", "adaptive"):
        rows = [row for row in detail_runs if row["arm"] == arm]
        gains = [row["true_mastery_gain"] for row in rows]
        errors = [row["final_estimate_error"] for row in rows]
        repeats = [row["question_repetition_rate"] for row in rows]
        covers = [row["topic_coverage"] for row in rows]
        weak_rates = [row["weak_topic_selection_rate"] for row in rows]
        mean = lambda values: sum(values) / len(values) if values else 0.0
        spread = lambda values: (sum((x - mean(values)) ** 2 for x in values) / len(values)) ** 0.5 if values else 0.0
        arms[arm] = {"mastery_gain_mean": mean(gains), "mastery_gain_stddev": spread(gains),
                     "estimate_error_mean": mean(errors), "estimate_error_stddev": spread(errors),
                     "repetition_rate_mean": mean(repeats), "topic_coverage_mean": mean(covers),
                     "weak_topic_selection_rate_mean": mean(weak_rates), "sample_size": len(rows)}
    return {"available": True, "runs": detail_runs, "arms": arms,
            "adaptive_gain_delta_vs_random": arms["adaptive"]["mastery_gain_mean"] - arms["random"]["mastery_gain_mean"],
            "profile_parameters": list(profiles), "seed": seed, "repeat_count": runs,
            "sessions": sessions, "questions_per_session": questions_per_session,
            "question_bank_size": len(questions), "topic_count": len(by_topic)}


def simulate_service_path(topic_material: dict[str, list[str]], *, sessions: int = 5,
                          questions_per_session: int = 1, runs: int = 1, seed: int = 17,
                          profiles: tuple[dict, ...] = PROFILES) -> dict:
    """Exercise the production assessment/attempt/BKT services in a disposable SQLite database.

    The input is explicitly supplied source material. A temporary database is created here and
    never accepts a caller's Session, so this path cannot write into a user's database. Learner
    responses and mastery trajectories are synthetic, not measured learning gains.
    """
    if (not topic_material or any(not texts for texts in topic_material.values()) or
            sessions < 1 or questions_per_session < 1 or runs < 1 or not profiles):
        return {"available": False, "reason": "Synthetic source material is required."}

    from app import models as _models  # noqa: F401  (register all tables on Base)
    from app.database.session import Base
    from app.models.assessment import Assessment, AssessmentAttempt, StudentAnswer
    from app.models.course import Course, Document
    from app.models.knowledge import ContentChunk, Topic
    from app.models.learner import RevisionRecommendation, TopicMasteryHistory
    from app.models.user import User
    from app.services.assessment import service
    from app.services.providers.embeddings import LocalHashEmbedding

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    aggregate = {"assessments_created": 0, "attempts_submitted": 0, "graded_answers": 0,
                 "mastery_events": 0, "learners": 0}
    trajectories = []
    try:
        with Session(engine, expire_on_commit=False) as db:
            course_id = uuid.uuid4()
            owner = User(email="simulation-owner@invalid.local", name="Synthetic Simulation", password_hash="disabled")
            db.add(owner)
            db.flush()
            course = Course(id=course_id, owner_id=owner.id, title="Synthetic evaluation course", description="")
            db.add(course)
            topics = {}
            for index, (name, texts) in enumerate(topic_material.items()):
                topic = Topic(course_id=course.id, name=name, description="Synthetic test topic")
                db.add(topic)
                db.flush()
                topics[name] = topic
                document = Document(course_id=course.id, original_filename=f"synthetic-{index}.txt",
                                    stored_path=f"synthetic/{index}.txt", source_type="transcript",
                                    mime_type="text/plain", size_bytes=sum(map(len, texts)), sha256=f"{index:064x}")
                db.add(document)
                db.flush()
                for chunk_index, text in enumerate(texts):
                    db.add(ContentChunk(course_id=course.id, document_id=document.id, topic_id=topic.id,
                                        chunk_index=chunk_index, source_type="transcript", text=text))
            db.flush()
            aggregate["learners"] = len(profiles) * runs * 2
            topic_ids = {name: topic.id for name, topic in topics.items()}
            if not topic_ids:
                return {"available": False, "reason": "No synthetic topics were provided."}

            for profile_index, profile in enumerate(profiles):
              for run_index in range(runs):
                for arm_index, arm in enumerate(("random", "adaptive")):
                    learner = User(email=f"sim-{profile_index}-{run_index}-{arm}@invalid.local", name=profile["name"], password_hash="disabled")
                    db.add(learner)
                    db.flush()
                    rng = random.Random(seed + profile_index * 1_000_003 + run_index * 10_007 + arm_index * 997)
                    truth = {topic_id: min(.98, max(.02, profile["skill"] + rng.uniform(-.06, .06)))
                             for topic_id in topic_ids.values()}
                    initial_true_mastery = sum(truth.values()) / len(truth)
                    sessions_rows = []
                    total_score = total_answers = 0
                    presented = set()
                    repeated_presentations = 0
                    relevant_recommendations = recommendation_count = 0
                    previous_session_topics = set()
                    covered_topics = set()
                    for session_index in range(sessions):
                        if session_index:
                            for topic_id in truth.keys() - previous_session_topics:
                                truth[topic_id] *= 1 - profile["forgetting"]
                        session_topics = set()
                        for question_index in range(questions_per_session):
                            if arm == "random":
                                selected_topic_ids = [rng.choice(list(topic_ids.values()))]
                            else:
                                selected_topic_ids = list(topic_ids.values())
                            try:
                                assessment, questions, _report = service.create_assessment(
                                    db, user=learner, course_id=course.id, mode="quiz", topic_ids=selected_topic_ids,
                                    n=1, difficulty="medium", types=["short_answer"], timed=False, minutes=None,
                                    embedder=LocalHashEmbedding(768), llm=None,
                                    seed=seed + profile_index * 1_000_003 + run_index * 100_003 + arm_index * 10_007 + session_index * 101 + question_index,
                                )
                            except service.AssessmentError as exc:
                                db.rollback()
                                return {"available": False,
                                        "reason": f"Production assessment service could not create another verified synthetic question: {exc}",
                                        "evidence": aggregate}
                            if not questions:
                                return {"available": False, "reason": "Production assessment service could not create a verified synthetic question.",
                                        "evidence": aggregate}
                            attempt = service.start_attempt(db, learner, assessment)
                            question = questions[0]
                            if question.verification_status != "verified":
                                return {"available": False, "reason": "Assessment service returned an unverified synthetic question.",
                                        "evidence": aggregate}
                            normalized_question = question.normalized_text
                            repeated_presentations += int(normalized_question in presented)
                            presented.add(normalized_question)
                            session_topics.add(question.topic_id)
                            covered_topics.add(question.topic_id)
                            mastery = truth[question.topic_id]
                            p_correct = mastery * (1 - profile["slip"]) + (1 - mastery) * profile["guess"]
                            intended_correct = rng.random() < p_correct
                            answers = question.answer_key.get("answers", [])
                            response = ", ".join(answers) if intended_correct and answers else "simulated incorrect response"
                            service.submit_attempt(db, learner, attempt, assessment, {question.id: response})
                            open_recommendations = db.scalars(select(RevisionRecommendation).where(
                                RevisionRecommendation.user_id == learner.id,
                                RevisionRecommendation.course_id == course.id,
                                RevisionRecommendation.status == "open",
                            )).all()
                            eligible_recommendations = [rec for rec in open_recommendations
                                                        if rec.kind != "assess_topic" and rec.topic_id in truth]
                            recommendation_count += len(eligible_recommendations)
                            relevant_recommendations += sum(
                                truth[rec.topic_id] < 0.40 for rec in eligible_recommendations
                            )
                            total_score += attempt.score or 0.0
                            total_answers += 1
                            aggregate["assessments_created"] += 1
                            aggregate["attempts_submitted"] += 1
                            aggregate["graded_answers"] += 1
                            for topic_id in truth:
                                if topic_id == question.topic_id:
                                    truth[topic_id] = min(.98, truth[topic_id] + (1 - truth[topic_id]) * profile["learning"])
                        previous_session_topics = session_topics
                        persisted_mastery = service.latest_mastery(db, learner.id, list(topic_ids.values()))
                        estimate = sum(persisted_mastery[t].mastery if t in persisted_mastery else bkt.P_INIT
                                       for t in topic_ids.values()) / len(topic_ids)
                        sessions_rows.append({"session": session_index + 1,
                                              "synthetic_true_mastery": sum(truth.values()) / len(truth),
                                              "synthetic_mastery_gain": sum(truth.values()) / len(truth) - initial_true_mastery,
                                              "production_bkt_estimate": estimate,
                                              "topics_practiced": len(session_topics),
                                              "topic_coverage": len(covered_topics) / len(topic_ids),
                                              "repeated_presentations": repeated_presentations,
                                              "mean_grade": total_score / total_answers if total_answers else 0.0})
                    trajectories.append({"profile": profile["name"], "run": run_index + 1, "arm": arm, "sessions": sessions_rows,
                                         "initial_synthetic_true_mastery": initial_true_mastery,
                                         "question_repetition_rate": repeated_presentations / total_answers if total_answers else 0.0,
                                         "recommendation_weak_topic_precision": (
                                             relevant_recommendations / recommendation_count if recommendation_count else None
                                         ),
                                         "recommendation_count": recommendation_count,
                                         "topic_coverage": len(covered_topics) / len(topic_ids),
                                         "final_estimate_error": sessions_rows[-1]["production_bkt_estimate"] - sessions_rows[-1]["synthetic_true_mastery"] if sessions_rows else None,
                                         "final_absolute_estimate_error": abs(sessions_rows[-1]["production_bkt_estimate"] - sessions_rows[-1]["synthetic_true_mastery"]) if sessions_rows else None})
            db.flush()
            aggregate["mastery_events"] = db.scalar(select(func.count()).select_from(TopicMasteryHistory)) or 0
            aggregate["assessments_created"] = db.scalar(select(func.count()).select_from(Assessment)) or 0
            aggregate["attempts_submitted"] = db.scalar(select(func.count()).select_from(AssessmentAttempt)
                                                        .where(AssessmentAttempt.submitted_at.is_not(None))) or 0
            aggregate["graded_answers"] = db.scalar(select(func.count()).select_from(StudentAnswer)) or 0
            arm_metrics = {}
            for arm in ("random", "adaptive"):
                rows = [row for row in trajectories if row["arm"] == arm]
                gains = [row["sessions"][-1]["synthetic_true_mastery"] - row["initial_synthetic_true_mastery"] for row in rows]
                def summary(values):
                    average = sum(values) / len(values) if values else None
                    deviation = (sum((value - average) ** 2 for value in values) / len(values)) ** .5 if values else None
                    return average, deviation
                repetition_mean, repetition_sd = summary([row["question_repetition_rate"] for row in rows])
                coverage_mean, coverage_sd = summary([row["topic_coverage"] for row in rows])
                error_mean, error_sd = summary([row["final_absolute_estimate_error"] for row in rows])
                gain_mean, gain_sd = summary(gains)
                signed_error_mean, signed_error_sd = summary([row["final_estimate_error"] for row in rows])
                recommendation_rows = [row for row in rows if row["recommendation_weak_topic_precision"] is not None]
                recommendation_mean, recommendation_sd = summary(
                    [row["recommendation_weak_topic_precision"] for row in recommendation_rows]
                )
                arm_metrics[arm] = {"sample_size": len(rows),
                                    "question_repetition_rate_mean": repetition_mean,
                                    "question_repetition_rate_stddev": repetition_sd,
                                    "topic_coverage_mean": coverage_mean,
                                    "topic_coverage_stddev": coverage_sd,
                                    "final_estimate_error_mean": signed_error_mean,
                                    "final_estimate_error_stddev": signed_error_sd,
                                    "final_absolute_estimate_error_mean": error_mean,
                                    "final_absolute_estimate_error_stddev": error_sd,
                                    "synthetic_mastery_gain_mean": gain_mean,
                                    "synthetic_mastery_gain_stddev": gain_sd,
                                    "recommendation_weak_topic_precision_mean": recommendation_mean,
                                    "recommendation_weak_topic_precision_stddev": recommendation_sd,
                                    "recommendation_sample_size": len(recommendation_rows)}
            return {"available": True, "synthetic_only": True, "service_path": ["create_assessment", "start_attempt", "submit_attempt", "grade_answer", "record_answer", "BKT update"],
                    "evidence": aggregate, "trajectories": trajectories, "arms": arm_metrics, "seed": seed,
                    "sessions": sessions, "questions_per_session": questions_per_session, "repeat_count": runs,
                    "topic_count": len(topic_ids)}
    finally:
        engine.dispose()
