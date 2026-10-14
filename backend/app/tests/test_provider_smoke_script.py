import json

from app.services.providers.embeddings import LocalHashEmbedding
from scripts.check_providers import _numerical_check, _temporary_course, _topic_check


class Replies:
    def __init__(self, values):
        self.values = iter(values)

    def complete(self, *_args, **_kwargs):
        return next(self.values)


def test_provider_script_learning_smokes_use_existing_topic_and_verification_paths():
    engine, db, user, course, chunks = _temporary_course()
    try:
        topic_response = {
            "topics": [
                {"name": "Algebra", "description": "Linear expressions", "chunks": [0]},
                {"name": "Calculus", "description": "Derivatives", "chunks": [1]},
                {"name": "Mechanics", "description": "Work and motion", "chunks": [2]},
            ],
            "prerequisites": [
                {"topic": "Calculus", "requires": "Algebra"},
                {"topic": "Mechanics", "requires": "Calculus"},
            ],
        }
        assert "2 prerequisite link(s)" in _topic_check(db, course, chunks, Replies([json.dumps(topic_response)]))

        candidate = {
            "question": "Using the work formula W = F * d from mechanics, calculate work W in joules when a constant force F of 8 newtons acts along a distance d of 3 metres.",
            "variables": {"F": 8, "d": 3},
            "expression": "F * d",
            "unit": "joules",
            "explanation": "Work is force multiplied by distance, so 8 times 3 is 24 joules.",
        }
        verdict = {"answer_supported": True, "unique_answer": True}
        llm = Replies([json.dumps(candidate), json.dumps(verdict)])
        detail = _numerical_check(db, user, course, chunks, LocalHashEmbedding(768), llm)
        assert "passed" in detail and "checks" in detail
    finally:
        db.close()
        engine.dispose()
