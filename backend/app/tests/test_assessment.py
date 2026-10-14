"""Assessment generation, verification, grading, duplicate prevention, submission and isolation."""
import json
import re
import uuid

import pytest
from sqlalchemy import func, select

from app.models.assessment import Assessment, AssessmentQuestion, Question, QuestionSource, StudentAnswer
from app.models.knowledge import ContentChunk
from app.models.learner import TopicMasteryHistory
from app.services.assessment.common import Candidate, normalize
from app.services.assessment.dedupe import DuplicateIndex
from app.services.assessment.grade import grade_answer, parse_number
from app.services.assessment.safe_eval import EvalError, safe_eval
from app.services.assessment.verify import verify_candidate
from app.services.providers.embeddings import LocalHashEmbedding
from app.services.assessment.service import _eligible_assessment_chunk
from app.services.assessment.llm_gen import SYSTEM as LLM_QUESTION_SYSTEM
from app.tests import samples
from app.tests.conftest import upload
from app.tests.fakes import ScriptLLM


def test_generated_figure_assessment_chunk_requires_llm_and_figure_reference():
    from types import SimpleNamespace

    text_chunk = SimpleNamespace(text="A sufficiently long source passage for question generation.", is_generated_description=False, figure_ref=None)
    figure_chunk = SimpleNamespace(text="A sufficiently long OCR or generated figure description for question generation.", is_generated_description=True, figure_ref="page:2:image:1")
    orphan_figure_chunk = SimpleNamespace(text=figure_chunk.text, is_generated_description=True, figure_ref=None)

    assert _eligible_assessment_chunk(text_chunk, None)
    assert not _eligible_assessment_chunk(figure_chunk, None)
    assert _eligible_assessment_chunk(figure_chunk, object())
    assert not _eligible_assessment_chunk(orphan_figure_chunk, object())

BIG = [
    "The first law of thermodynamics states that energy is conserved in every process. Heat added to a system equals the change in internal energy plus the work done.",
    "Entropy measures the disorder of a system. The second law says the entropy of an isolated system never decreases over time.",
    "The Carnot cycle is the most efficient heat engine possible. Carnot efficiency depends only on the temperatures of the hot and cold reservoirs.",
    "A refrigerator moves heat from a cold region to a hot region using external work. The coefficient of performance compares heat removed with work supplied.",
    "Enthalpy is the heat content of a system at constant pressure. Chemical reactions release or absorb enthalpy depending on bond energies.",
    "Thermal conductivity describes how quickly heat travels through a material. Metals conduct heat much faster than insulating foam does.",
]


@pytest.fixture
def big(client, alice, course):
    """A course with enough real, distinct material to generate several verified questions."""
    upload(client, alice, course["id"], "thermo_big.pdf", samples.make_text_pdf(BIG))
    upload(client, alice, course["id"], "lecture.vtt", samples.VTT)
    return course


def quiz(client, headers, cid, **kw):
    body = {"mode": "quiz", "num_questions": 4, "types": ["mcq", "short_answer"], "seed": 7, **kw}
    return client.post(f"/api/courses/{cid}/assessments", headers=headers, json=body)


def qrows(db, assessment_id):
    return list(db.scalars(select(Question).join(AssessmentQuestion, AssessmentQuestion.question_id == Question.id)
                           .where(AssessmentQuestion.assessment_id == uuid.UUID(assessment_id)).order_by(AssessmentQuestion.position)))


def answers_for(db, assessment_id, *, correct=True):
    out = {}
    for q in qrows(db, assessment_id):
        if q.question_type == "mcq":
            out[str(q.id)] = q.answer_key["correct"] if correct else next(o["id"] for o in q.options if o["id"] != q.answer_key["correct"])
        elif q.question_type == "short_answer":
            out[str(q.id)] = ", ".join(q.answer_key["answers"]) if correct else "something completely unrelated"
        else:
            out[str(q.id)] = str(q.answer_key["value"]) if correct else "123456"
    return out


def take(client, headers, db, aid, *, correct=True, answers=None):
    att = client.post(f"/api/assessments/{aid}/attempts", headers=headers).json()
    r = client.post(f"/api/attempts/{att['attempt_id']}/submit", headers=headers, json={"answers": answers if answers is not None else answers_for(db, aid, correct=correct)})
    return att, r


# ---------------- generation + verification ----------------
def test_llm_difficulty_prompt_calibrates_cognitive_depth_independently_of_format():
    prompt = LLM_QUESTION_SYSTEM.format(difficulty="hard", qtype="mcq", schema="schema", language="English")
    hand_labeled_calibration = {
        "easy": "recall or recognize one fact stated directly",
        "medium": "explain a relationship stated in the SOURCE or apply one stated rule",
        "hard": "combine multiple facts or conditions from the SOURCE",
    }
    for label, criterion in hand_labeled_calibration.items():
        assert f"{label}: {criterion}" in prompt
    assert "not question format" in prompt
    assert "return {\"skip\": true}" in prompt


def test_offline_questions_are_verified_sourced_and_tagged(client, alice, big, db):
    r = quiz(client, alice, big["id"], num_questions=6)
    assert r.status_code == 201, r.text
    a = r.json()
    assert len(a["questions"]) >= 4 and a["generation"] == "cloze"
    for q in qrows(db, a["id"]):
        assert q.verification_status == "verified" and q.generation_method == "cloze" and q.topic_id is not None
        assert q.difficulty in ("easy", "medium", "hard") and all(q.verification["checks"].values())
        (src,) = db.scalars(select(ContentChunk).join(QuestionSource, QuestionSource.chunk_id == ContentChunk.id).where(QuestionSource.question_id == q.id)).all()
        assert q.explanation.startswith("The source states:") and q.explanation[len("The source states: \u201c"):-1] in src.text
        if q.question_type == "mcq":
            assert q.difficulty == "easy" and len(q.options) == 4 and len({normalize(o["text"]) for o in q.options}) == 4
            right = next(o for o in q.options if o["id"] == q.answer_key["correct"])
            has = lambda w: re.search(rf"\b{re.escape(w.lower())}\b", src.text.lower()) is not None   # whole word ("efficient" is not in "coefficient")
            assert has(right["text"])                                                          # correct answer is in the evidence
            assert not any(has(o["text"]) for o in q.options if o is not right)                # distractors are not
        else:
            assert q.difficulty in ("medium", "hard") and q.rubric["concepts"]
            assert all(c["accepted"][0].lower() in src.text.lower() for c in q.rubric["concepts"])


def test_student_view_never_leaks_answers(client, alice, big):
    a = quiz(client, alice, big["id"]).json()
    att = client.post(f"/api/assessments/{a['id']}/attempts", headers=alice).json()
    for payload in (a, client.get(f"/api/assessments/{a['id']}", headers=alice).json(), att):
        blob = json.dumps(payload)
        for banned in ("answer_key", "explanation", "rubric", "from_topic", "citations", "correct", "The source states", "verification"):
            assert banned not in blob, banned
    assert all(set(q) == {"id", "position", "text", "question_type", "difficulty", "topic_id", "topic_name", "options", "unit"} for q in a["questions"])


def test_numerical_requires_a_model_and_warns_otherwise(client, alice, big):
    r = quiz(client, alice, big["id"], types=["numerical", "mcq"])
    assert r.status_code == 201 and any("Numerical questions need a language model" in w for w in r.json()["warnings"])
    assert all(q["question_type"] == "mcq" for q in r.json()["questions"])
    assert quiz(client, alice, big["id"], types=["numerical"]).status_code == 422


def _numeric_llm(question_text, variables, expression, verifier_ok=True):
    def fn(system, user):
        if system.startswith("You check a quiz"):
            return json.dumps({"answer_supported": verifier_ok, "unique_answer": True})
        return json.dumps({"question": question_text, "variables": variables, "expression": expression, "unit": "", "explanation": "Apply the Carnot relation."})
    return ScriptLLM(fn)


def test_numerical_question_is_computed_deterministically(client, alice, big, db, monkeypatch):
    llm = _numeric_llm("A Carnot engine runs between a hot reservoir at 500 K and a cold reservoir at 300 K. What is its maximum efficiency?",
                       {"T_h": 500, "T_c": 300}, "1 - T_c/T_h")
    monkeypatch.setattr("app.api.assessments.get_llm", lambda: llm)
    r = quiz(client, alice, big["id"], types=["numerical"], num_questions=1)
    assert r.status_code == 201, r.text
    (q,) = qrows(db, r.json()["id"])
    assert q.question_type == "numerical" and q.generation_method == "llm" and abs(q.answer_key["value"] - 0.4) < 1e-12
    _, res = take(client, alice, db, r.json()["id"], answers={str(q.id): "0.401"})  # within the stated 1% tolerance
    assert res.json()["questions"][0]["is_correct"] is True
    assert res.json()["questions"][0]["correct_answer"] == "0.4"


def test_numerical_with_missing_input_or_unsafe_expression_is_rejected(client, alice, big, monkeypatch):
    for text, variables, expr in [("What is the efficiency at 500 K hot?", {"T_h": 500, "T_c": 300}, "1 - T_c/T_h"),   # 300 not stated
                                  ("The hot side is 500 K and the cold side 300 K. Efficiency?", {"T_h": 500, "T_c": 300}, "__import__('os').system('x')")]:
        monkeypatch.setattr("app.api.assessments.get_llm", lambda llm=_numeric_llm(text, variables, expr): llm)
        assert quiz(client, alice, big["id"], types=["numerical"], num_questions=1).status_code == 422


def test_second_model_can_veto_a_question(client, alice, big, monkeypatch):
    def fn(system, user):
        if system.startswith("You check a quiz"):
            return json.dumps({"answer_supported": False, "unique_answer": True})
        if "entropy" not in user.lower():
            return json.dumps({"skip": True})
        return json.dumps({"question": "What does the second law say entropy of an isolated system does?", "options": ["never decreases", "always decreases", "stays zero", "doubles"],
                           "correct_index": 0, "explanation": "Stated in the source."})
    monkeypatch.setattr("app.api.assessments.get_llm", lambda: ScriptLLM(fn))
    assert quiz(client, alice, big["id"], types=["mcq"], num_questions=2).status_code == 422  # every proposal vetoed


def test_llm_mcq_accepted_when_verifiers_agree(client, alice, big, db, monkeypatch):
    def fn(system, user):
        if system.startswith("You check a quiz"):
            return json.dumps({"answer_supported": True, "unique_answer": True})
        if "entropy" not in user.lower():   # a passage-aware double: only writes a question the passage supports
            return json.dumps({"skip": True})
        return json.dumps({"question": "According to the notes, what happens to the entropy of an isolated system over time?",
                           "options": ["It never decreases", "It always decreases", "It oscillates", "It is undefined"], "correct_index": 0, "explanation": "Second law."})
    monkeypatch.setattr("app.api.assessments.get_llm", lambda: ScriptLLM(fn))
    r = quiz(client, alice, big["id"], types=["mcq"], num_questions=1)
    assert r.status_code == 201, r.text
    (q,) = qrows(db, r.json()["id"])
    assert q.generation_method == "llm" and q.verification["second_check"]["result"] is True


# ---------------- verification unit tests ----------------
def _mcq(options, correct="a", source="Entropy never decreases in an isolated system.", text="Which statement is true about entropy in an isolated system according to the source?"):
    return Candidate(text=text, qtype="mcq", difficulty="easy", answer_key={"correct": correct}, explanation="e", chunk_id=uuid.uuid4(), topic_id=uuid.uuid4(),
                     subtopic_id=None, method="llm", options=[{"id": "abcd"[i], "text": t} for i, t in enumerate(options)], source_text=source)


@pytest.mark.parametrize("opts,correct,fragment", [
    (["never decreases", "never decreases", "doubles", "halves"], "a", "duplicate"),
    (["increases forever", "doubles", "halves", "vanishes"], "a", "not supported by the source"),
    (["never decreases", "entropy isolated system", "halves", "vanishes"], "a", "also appears in the source"),
    (["never decreases", "doubles", "halves", "vanishes"], "z", "no unique correct option"),
])
def test_verifier_rejects_bad_mcq(opts, correct, fragment):
    ok, checks, why = verify_candidate(_mcq(opts, correct), has_topics=True)
    assert not ok and any(fragment in w for w in why), why


def test_verifier_accepts_good_mcq_and_rejects_off_topic_or_untagged():
    assert verify_candidate(_mcq(["never decreases", "doubles", "halves", "vanishes"]), has_topics=True)[0]
    assert not verify_candidate(_mcq(["never decreases", "doubles", "halves", "vanishes"], text="What colour is the sky above the mountains today for hikers?"), has_topics=True)[0]
    c = _mcq(["never decreases", "doubles", "halves", "vanishes"]); c.topic_id = None
    assert not verify_candidate(c, has_topics=True)[0] and verify_candidate(c, has_topics=False)[0]


def test_short_answer_rubric_must_be_supported_by_source():
    base = dict(text="Fill in the blank to describe what the second law says about entropy here.", qtype="short_answer", difficulty="medium", explanation="e", chunk_id=uuid.uuid4(),
                topic_id=uuid.uuid4(), subtopic_id=None, method="cloze", source_text="Entropy never decreases in an isolated system.", answer_key={"answers": ["x"]})
    assert verify_candidate(Candidate(rubric={"concepts": [{"name": "entropy", "accepted": ["entropy"]}]}, **base), has_topics=True)[0]
    assert not verify_candidate(Candidate(rubric={"concepts": [{"name": "enthalpy", "accepted": ["enthalpy"]}]}, **base), has_topics=True)[0]
    assert not verify_candidate(Candidate(rubric=None, **base), has_topics=True)[0]


def test_safe_eval_allows_math_and_blocks_everything_else():
    assert abs(safe_eval("1 - Tc/Th", {"Tc": 300, "Th": 500}) - 0.4) < 1e-12
    assert abs(safe_eval("sqrt(x) * pi", {"x": 4}) - 2 * 3.141592653589793) < 1e-9
    for bad in ["__import__('os')", "open('x')", "x.__class__", "[1,2]", "x if 1 else 2", "9**99", "1/0", "lambda: 1", "y"]:
        with pytest.raises(EvalError):
            safe_eval(bad, {"x": 1})


# ---------------- grading ----------------
def _q(qtype, **kw):
    return Question(course_id=uuid.uuid4(), text="t", normalized_text="t", question_type=qtype, difficulty="medium", explanation="e", answer_key=kw.pop("answer_key"), **kw)


def test_mcq_is_exact_match_and_blank_is_unanswered():
    q = _q("mcq", answer_key={"correct": "b"}, options=[{"id": "a", "text": "x"}, {"id": "b", "text": "y"}])
    assert grade_answer(q, {"value": "b"}).is_correct and not grade_answer(q, {"value": "a"}).is_correct
    g = grade_answer(q, {"value": ""})
    assert g.answered is False and g.score == 0


def test_short_answer_uses_rubric_with_partial_credit_and_stems():
    q = _q("short_answer", answer_key={"answers": ["entropy", "reservoirs"]}, rubric={"concepts": [{"name": "entropy", "accepted": ["entropy"]}, {"name": "reservoirs", "accepted": ["reservoirs", "reservoir"]}]})
    assert grade_answer(q, {"value": "Entropy and the Reservoir"}).score == 1.0
    g = grade_answer(q, {"value": "it is about entropy"})
    assert g.score == 0.5 and not g.is_correct and g.feedback["missing"] == ["reservoirs"]
    assert grade_answer(q, {"value": "The system becomes more disordered over time, which is a deep and fluent idea."}).score == 0.0  # fluent != correct
    assert grade_answer(q, {"value": "entropy reservoirs " + "padding " * 100}).score == 0.5  # too long: credit capped


def test_submit_passes_question_source_to_optional_partial_answer_reviewer(client, alice, big, db, monkeypatch):
    captured = []

    class CapturingLLM:
        def complete(self, system, user, *, json_mode=False, max_tokens=1200):
            captured.append((system, json.loads(user), json_mode))
            return '{"concepts": []}'

    response = quiz(client, alice, big["id"], num_questions=1, types=["short_answer"], difficulty="hard")
    assert response.status_code == 201, response.text
    question = qrows(db, response.json()["id"])[0]
    assert len(question.rubric["concepts"]) == 2
    answer = question.rubric["concepts"][0]["accepted"][0]
    source_id = db.scalar(select(QuestionSource.chunk_id).where(QuestionSource.question_id == question.id))
    source = db.get(ContentChunk, source_id)
    monkeypatch.setattr("app.api.assessments.get_llm", lambda: CapturingLLM())

    attempt = client.post(f"/api/assessments/{response.json()['id']}/attempts", headers=alice)
    result = client.post(f"/api/attempts/{attempt.json()['attempt_id']}/submit", headers=alice,
                         json={"answers": {str(question.id): answer}})

    assert result.status_code == 200, result.text
    assert captured and captured[0][1]["source"] == source.text
    assert captured[0][1]["student_answer"] == answer
    reviewed = next(row for row in result.json()["questions"] if row["id"] == str(question.id))
    assert reviewed["feedback"]["missing"] == [question.rubric["concepts"][1]["name"]]
    assert "llm_rubric_review" not in reviewed["feedback"]  # an empty model result changes no grade


def test_numerical_tolerance_and_parsing():
    q = _q("numerical", answer_key={"value": 0.4, "tolerance_rel": 0.01})
    assert grade_answer(q, {"value": "0.4"}).is_correct and grade_answer(q, {"value": "0.402"}).is_correct
    assert not grade_answer(q, {"value": "0.45"}).is_correct and not grade_answer(q, {"value": "about forty"}).is_correct
    assert parse_number("1,200 K") == 1200 and parse_number("-3.5e2") == -350 and parse_number("abc") is None


# ---------------- duplicates ----------------
def test_questions_are_not_repeated_across_assessments(client, alice, big, db):
    seen: set[str] = set()
    total = 0
    for seed in (1, 2, 3):
        r = quiz(client, alice, big["id"], num_questions=3, seed=seed)
        if r.status_code != 201:
            break
        for q in qrows(db, r.json()["id"]):
            n = normalize(q.text)
            assert n not in seen, "repeated question"
            seen.add(n); total += 1
    assert total >= 6
    # measured repetition rate across everything this student was given
    assert db.scalar(select(func.count()).select_from(Question)) == len({q.normalized_text for q in db.scalars(select(Question))})


def test_running_out_of_fresh_material_is_reported_not_hidden(client, alice, course, db):
    upload(client, alice, course["id"], "tiny.pdf", samples.make_text_pdf(BIG[:2]))
    first = quiz(client, alice, course["id"], num_questions=30)
    assert first.status_code == 201 and len(first.json()["questions"]) < 30
    assert any("Only" in w for w in first.json()["warnings"])
    second = quiz(client, alice, course["id"], num_questions=30, seed=99)
    assert second.status_code == 422 or len(second.json()["questions"]) < len(first.json()["questions"])


def test_duplicate_index_catches_exact_and_near_duplicates(db):
    class E:  # tiny embedder so the index logic is tested in isolation
        semantic = False
        def embed(self, texts): return LocalHashEmbedding(768).embed(texts)
    idx = DuplicateIndex.__new__(DuplicateIndex)
    idx.embedder, idx.thr, idx.norms, idx.vecs, idx.history_size = E(), 0.82, set(), [], 0
    text = "Which term best completes this statement? The second law says the _____ of an isolated system never decreases."
    dup, vec = idx.check(text); assert not dup
    idx.add(text, vec)
    assert idx.check(text)[0]                                                                   # exact
    assert idx.check(text.replace("Which term best completes", "Which term completes"))[0]      # near
    assert not idx.check("What does the Carnot cycle say about hot and cold reservoir temperatures?")[0]


# ---------------- attempts, learner model, recommendations ----------------
def test_submit_scores_updates_mastery_and_recommends(client, alice, big, db):
    a = quiz(client, alice, big["id"], num_questions=6).json()
    n = len(a["questions"])
    att, res = take(client, alice, db, a["id"], correct=True)
    r = res.json()
    assert res.status_code == 200 and r["score"] == n == r["max_score"] and r["accuracy"] == 1.0 and r["correct"] == n
    assert r["mastery_changes"] and all(c["after"] > c["before"] and c["before"] == pytest.approx(0.20) for c in r["mastery_changes"])  # starts at the 20% prior
    rows = db.scalars(select(TopicMasteryHistory)).all()
    assert len(rows) == n and all(h.attempt_id is not None and h.evidence["bkt"] and h.evidence["source_chunk_ids"] for h in rows)
    assert r["recommendations"] and all(x["evidence"] for x in r["recommendations"])
    for qn in r["questions"]:
        assert qn["explanation"] and qn["citations"] and qn["citations"][0]["page"] or qn["citations"][0]["start_seconds"] is not None
    assert r["next_assessment"]["mode"] == "quiz" and r["estimate_note"]


def test_wrong_answers_lower_mastery_and_explain_with_inferred_labels(client, alice, big, db):
    a = quiz(client, alice, big["id"], num_questions=6).json()
    _, res = take(client, alice, db, a["id"], correct=False)
    r = res.json()
    assert r["score"] == 0 and all(c["after"] < c["before"] for c in r["mastery_changes"])
    notes = [q["misconception"] for q in r["questions"] if q["misconception"]]
    assert notes and all(n.startswith("Inferred:") for n in notes)
    kinds = {x["kind"] for x in r["recommendations"]}
    assert "read_source" in kinds and "easier_practice" in kinds
    src = next(x for x in r["recommendations"] if x["kind"] == "read_source")
    assert src["chunk_id"] and src["evidence"]["mastery_estimate"] < 0.4


def test_unanswered_questions_give_no_mastery_evidence(client, alice, big, db):
    a = quiz(client, alice, big["id"], num_questions=4).json()
    _, res = take(client, alice, db, a["id"], answers={})
    r = res.json()
    assert r["score"] == 0 and r["answered"] == 0 and all(q["answered"] is False and q["is_correct"] is None for q in r["questions"])
    assert db.scalar(select(func.count()).select_from(TopicMasteryHistory)) == 0


def test_attempt_lifecycle_rules(client, alice, big, db):
    a = quiz(client, alice, big["id"]).json()
    att = client.post(f"/api/assessments/{a['id']}/attempts", headers=alice).json()
    assert client.post(f"/api/assessments/{a['id']}/attempts", headers=alice).json()["attempt_id"] == att["attempt_id"]   # resume, not a second attempt
    assert client.get(f"/api/attempts/{att['attempt_id']}", headers=alice).status_code == 409                              # no result before submit
    bad = {a["questions"][0]["id"]: "zzz"} if a["questions"][0]["question_type"] == "mcq" else {str(uuid.uuid4()): "x"}
    assert client.post(f"/api/attempts/{att['attempt_id']}/submit", headers=alice, json={"answers": bad}).status_code in (409, 422)
    ok = client.post(f"/api/attempts/{att['attempt_id']}/submit", headers=alice, json={"answers": answers_for(db, a["id"])})
    assert ok.status_code == 200
    assert client.post(f"/api/attempts/{att['attempt_id']}/submit", headers=alice, json={"answers": {}}).status_code == 409   # no double submit
    assert client.post(f"/api/assessments/{a['id']}/attempts", headers=alice).status_code == 409                              # no retake of seen questions
    assert client.get(f"/api/attempts/{att['attempt_id']}", headers=alice).json()["score"] == ok.json()["score"]            # reviewable later


def test_timed_mock_exam_flags_overtime(client, alice, big, db):
    a = quiz(client, alice, big["id"], mode="mock_exam", time_limit_minutes=5).json()
    assert a["timed"] is True and a["time_limit_seconds"] == 300
    att = client.post(f"/api/assessments/{a['id']}/attempts", headers=alice).json()
    from datetime import datetime, timedelta, timezone
    from app.models.assessment import AssessmentAttempt
    row = db.get(AssessmentAttempt, uuid.UUID(att["attempt_id"])); row.started_at = datetime.now(timezone.utc) - timedelta(seconds=400); db.commit()
    r = client.post(f"/api/attempts/{att['attempt_id']}/submit", headers=alice, json={"answers": answers_for(db, a["id"])}).json()
    assert r["timed"] and 90 < r["overtime_seconds"] < 110


def test_diagnostic_covers_every_topic_equally(client, alice, big, db):
    topics = client.get(f"/api/courses/{big['id']}/topics", headers=alice).json()
    assert len(topics) >= 2
    a = quiz(client, alice, big["id"], mode="diagnostic", num_questions=len(topics) * 2, difficulty="mixed").json()
    covered = {q["topic_id"] for q in a["questions"]}
    assert covered == {t["id"] for t in topics if t["chunk_count"] > 0}


def test_quiz_adapts_toward_weak_topics(client, alice, big, db):
    topics = [t for t in client.get(f"/api/courses/{big['id']}/topics", headers=alice).json() if t["chunk_count"] > 0]
    weak, strong = max(topics, key=lambda t: t["chunk_count"]), min(topics, key=lambda t: t["chunk_count"])
    assert weak["id"] != strong["id"]
    from app.models.user import User
    uid = db.scalar(select(User.id))
    for tid, m in ((weak["id"], 0.08), (strong["id"], 0.95)):
        db.add(TopicMasteryHistory(user_id=uid, topic_id=uuid.UUID(tid), previous_mastery=0.2, new_mastery=m, was_correct=m > 0.5, difficulty="easy", evidence={})); db.commit()
    a = quiz(client, alice, big["id"], num_questions=6).json()
    counts = {t["id"]: sum(1 for q in a["questions"] if q["topic_id"] == t["id"]) for t in topics}
    assert counts[weak["id"]] > counts[strong["id"]], counts


def test_topic_selection_restricts_questions(client, alice, big):
    topics = client.get(f"/api/courses/{big['id']}/topics", headers=alice).json()
    t = max(topics, key=lambda x: x["chunk_count"])
    a = quiz(client, alice, big["id"], topic_ids=[t["id"]], num_questions=3).json()
    assert {q["topic_id"] for q in a["questions"]} == {t["id"]}
    other = client.post("/api/courses", json={"title": "Other"}, headers=alice).json()
    foreign = client.post(f"/api/courses/{other['id']}/topics", headers=alice, json={"name": "F"}).json()
    assert quiz(client, alice, big["id"], topic_ids=[foreign["id"]]).status_code == 400


def test_empty_course_and_invalid_requests(client, alice, course):
    assert quiz(client, alice, course["id"]).status_code == 422
    assert client.post(f"/api/courses/{course['id']}/assessments", headers=alice, json={"num_questions": 0}).status_code == 422
    assert client.post(f"/api/courses/{course['id']}/assessments", headers=alice, json={"types": []}).status_code == 422
    assert client.post(f"/api/courses/{course['id']}/assessments", headers=alice, json={"difficulty": "impossible"}).status_code == 422


def test_results_cite_real_sources_and_flag_removed_ones(client, alice, big, db):
    a = quiz(client, alice, big["id"], num_questions=3).json()
    att, res = take(client, alice, db, a["id"])
    assert all(q["citations"] and q["citations"][0]["available"] for q in res.json()["questions"])
    docs = client.get(f"/api/courses/{big['id']}/documents", headers=alice).json()
    for d in docs:
        client.delete(f"/api/documents/{d['id']}", headers=alice)
    again = client.get(f"/api/attempts/{att['attempt_id']}", headers=alice).json()
    assert all(q["source_removed"] and q["citations"] == [] and q["explanation"] for q in again["questions"])


# ---------------- isolation ----------------
def test_other_users_cannot_see_or_use_assessments(client, alice, bob, big, db):
    a = quiz(client, alice, big["id"]).json()
    att = client.post(f"/api/assessments/{a['id']}/attempts", headers=alice).json()
    assert quiz(client, bob, big["id"]).status_code == 404
    for method, path in [("get", f"/api/assessments/{a['id']}"), ("post", f"/api/assessments/{a['id']}/attempts"), ("get", f"/api/attempts/{att['attempt_id']}"),
                         ("get", f"/api/courses/{big['id']}/analytics"), ("get", f"/api/courses/{big['id']}/attempts"), ("get", f"/api/courses/{big['id']}/assessments"),
                         ("get", f"/api/courses/{big['id']}/recommendations"), ("get", f"/api/courses/{big['id']}/next-assessment")]:
        assert getattr(client, method)(path, headers=bob).status_code == 404, path
    assert client.post(f"/api/attempts/{att['attempt_id']}/submit", headers=bob, json={"answers": {}}).status_code == 404
    assert client.get(f"/api/assessments/{a['id']}").status_code == 401
