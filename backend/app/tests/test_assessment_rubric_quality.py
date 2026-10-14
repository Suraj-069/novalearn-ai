"""Short-answer rubric matching should reward stated concepts, not loose word overlap."""
import uuid
import json

from app.models.assessment import Question
from app.services.assessment.grade import grade_answer, grade_short_answer_with_llm


def _question(accepted: list[str]) -> Question:
    return Question(
        course_id=uuid.uuid4(),
        text="Explain the concept.",
        normalized_text="explain the concept",
        question_type="short_answer",
        difficulty="medium",
        explanation="The source describes energy transfer.",
        answer_key={"answers": [accepted[0]]},
        rubric={"concepts": [{"name": accepted[0], "accepted": accepted}]},
    )


def test_rubric_requires_accepted_words_to_appear_as_a_phrase():
    q = _question(["energy transfer"])

    assert grade_answer(q, {"value": "Energy transfer moves through the system."}).is_correct
    assert grade_answer(q, {"value": "Energy can move; transfer happens in the system."}).score == 0.0


def test_directly_negated_rubric_phrase_does_not_receive_credit():
    q = _question(["entropy"])

    assert grade_answer(q, {"value": "The answer is not entropy."}).score == 0.0
    assert grade_answer(q, {"value": "Entropy increases in this process."}).is_correct


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, system, user, *, json_mode=False, max_tokens=1200):
        self.calls.append((system, json.loads(user), json_mode, max_tokens))
        return self.response


def _two_concept_question() -> Question:
    q = _question(["energy transfer"])
    q.rubric = {"concepts": [
        {"name": "energy transfer", "accepted": ["energy transfer"]},
        {"name": "organized forces", "accepted": ["organized forces"]},
    ]}
    q.answer_key = {"answers": ["energy transfer", "organized forces"]}
    q.text = "Explain how work transfers energy."
    return q


def test_llm_can_award_bounded_partial_credit_for_source_supported_paraphrase():
    q = _two_concept_question()
    answer = {"value": "Energy transfer occurs when force moves energy."}
    llm = FakeLLM(json.dumps({"concepts": [{
        "name": "organized forces", "earned": True,
        "evidence": "force moves energy", "reason": "This paraphrases transfer by an applied force.",
    }]}))

    graded = grade_short_answer_with_llm(q, answer,
        "Work transfers energy through organized forces.", llm)

    assert grade_answer(q, answer).score == 0.5
    assert graded.score == 0.75 and not graded.is_correct
    assert graded.feedback["missing"] == []
    assert graded.feedback["llm_rubric_review"]["score_adjustment"] == 0.25
    assert graded.feedback["llm_rubric_review"]["rationales"][0]["evidence"] == "force moves energy"
    assert llm.calls[0][1]["source"] == "Work transfers energy through organized forces."
    assert llm.calls[0][2] is True


def test_llm_rubric_review_rejects_unrequested_concepts_and_unquoted_evidence():
    q = _two_concept_question()
    llm = FakeLLM(json.dumps({"concepts": [
        {"name": "unlisted concept", "earned": True, "evidence": "Energy transfer", "reason": "outside rubric"},
        {"name": "organized forces", "earned": True, "evidence": "the answer implies forces", "reason": "paraphrase"},
    ]}))

    graded = grade_short_answer_with_llm(q, {"value": "Energy transfer occurs."}, "Work uses forces.", llm)

    assert graded.score == 0.5
    assert "llm_rubric_review" not in graded.feedback


def test_llm_rubric_review_falls_back_on_bad_json_and_skips_overlong_answer():
    q = _two_concept_question()
    broken = FakeLLM("not-json")
    answer = {"value": "Energy transfer occurs."}
    assert grade_short_answer_with_llm(q, answer, "Work uses forces.", broken).score == 0.5

    overlong = FakeLLM('{"concepts": []}')
    result = grade_short_answer_with_llm(q, {"value": "Energy transfer " + ("padding " * 100)},
                                         "Work uses forces.", overlong)
    assert result.score == 0.5
    assert overlong.calls == []


def test_llm_review_does_not_clear_missing_concepts_without_increasing_capped_score():
    q = _question(["one"])
    names = ["one", "two", "three", "four"]
    q.rubric = {"concepts": [{"name": name, "accepted": [name]} for name in names]}
    q.answer_key = {"answers": names}
    answer = {"value": "one two three"}
    llm = FakeLLM(json.dumps({"concepts": [{
        "name": "four", "earned": True, "evidence": "four", "reason": "The response says four.",
    }]}))

    result = grade_short_answer_with_llm(q, answer, "The source covers four concepts.", llm)

    assert result.score == 0.75
    assert result.feedback["missing"] == ["four"]
    assert "llm_rubric_review" not in result.feedback

