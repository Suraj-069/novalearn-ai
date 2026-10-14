import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "evaluation" / "scripts" / "build_testset.py"
spec = importlib.util.spec_from_file_location("build_testset", SCRIPT)
build_testset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_testset)

RUN_SCRIPT = Path(__file__).resolve().parents[3] / "evaluation" / "scripts" / "run_rag_eval.py"
run_spec = importlib.util.spec_from_file_location("run_rag_eval", RUN_SCRIPT)
run_rag_eval = importlib.util.module_from_spec(run_spec)
run_spec.loader.exec_module(run_rag_eval)


def _item(**updates):
    item = {"id": "sample", "question": "What does the source explain?", "reference_answer": "Energy is conserved.",
            "ground_truth_chunk_ids": ["00000000-0000-0000-0000-000000000001"], "source_locations": [],
            "category": "factual", "expected_behavior": "answer", "review_status": "unreviewed"}
    return {**item, **updates}


def test_testset_items_are_schema_checked_and_unreviewed_answer_cases_require_source():
    build_testset.validate_item(_item())
    with pytest.raises(ValueError, match="require a reference answer"):
        build_testset.validate_item(_item(reference_answer="", ground_truth_chunk_ids=[]))


def test_refusal_items_cannot_claim_ground_truth_sources():
    item = _item(category="off-material", expected_behavior="refuse", reference_answer="", ground_truth_chunk_ids=[])
    build_testset.validate_item(item)
    with pytest.raises(ValueError, match="no source labels"):
        build_testset.validate_item({**item, "ground_truth_chunk_ids": ["00000000-0000-0000-0000-000000000001"]})


def test_rag_runner_only_accepts_approved_items_and_maps_refusals(tmp_path):
    record = _item(review_status="approved")
    path = tmp_path / "approved.jsonl"
    path.write_text(__import__("json").dumps(record) + "\n", encoding="utf-8")
    loaded = run_rag_eval.load_approved(path)[0]
    assert loaded["relevant_chunk_ids"] == record["ground_truth_chunk_ids"]
    assert loaded["category"] == "factual"
    path.write_text(__import__("json").dumps({**record, "review_status": "unreviewed"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="only approved"):
        run_rag_eval.load_approved(path)


def test_ragas_input_filters_unanswered_and_off_material_cases():
    run = {"metrics": [{"name": "case_details", "available": True, "details": {"cases": [
        {"question": "Grounded question?", "answer": "Grounded response.", "reference_answer": "Reference.",
         "retrieved_contexts": ["Actual indexed source."], "should_refuse": False},
        {"question": "Unavailable response?", "answer": None, "reference_answer": "Reference.",
         "retrieved_contexts": ["Actual indexed source."], "should_refuse": False},
        {"question": "Off material?", "answer": "Refusal.", "reference_answer": None,
         "retrieved_contexts": [], "should_refuse": True},
    ]}}]}
    rows = run_rag_eval.answerable_ragas_rows(run)
    assert rows == [{"user_input": "Grounded question?", "response": "Grounded response.",
                     "reference": "Reference.", "retrieved_contexts": ["Actual indexed source."]}]


def test_ragas_uses_framework_collections_and_configured_gemini(monkeypatch):
    calls = []

    class FakeMetric:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def ascore(self, **kwargs):
            calls.append((self.kwargs, kwargs))
            return SimpleNamespace(value=0.75)

    google = ModuleType("google")
    google.genai = SimpleNamespace(Client=lambda **kwargs: SimpleNamespace(**kwargs))
    ragas_embeddings = ModuleType("ragas.embeddings")
    ragas_embeddings.GoogleEmbeddings = lambda **kwargs: SimpleNamespace(**kwargs)
    ragas_llms = ModuleType("ragas.llms")
    ragas_llms.llm_factory = lambda *args, **kwargs: SimpleNamespace(model=args[0], **kwargs)
    collections = ModuleType("ragas.metrics.collections")
    for name in ("AnswerRelevancy", "ContextPrecision", "ContextRecall", "Faithfulness"):
        setattr(collections, name, FakeMetric)
    for name, module in {"google": google, "google.genai": ModuleType("google.genai"),
                         "ragas": ModuleType("ragas"), "ragas.embeddings": ragas_embeddings,
                         "ragas.llms": ragas_llms, "ragas.metrics": ModuleType("ragas.metrics"),
                         "ragas.metrics.collections": collections}.items():
        monkeypatch.setitem(sys.modules, name, module)
    config_module = sys.modules["app.core.config"]
    monkeypatch.setattr(config_module, "get_settings", lambda: SimpleNamespace(
        llm_provider="google", llm_api_key="test-key", llm_model="gemini-test",
        embedding_model="gemini-embedding-001"))
    run = {"metrics": [{"name": "case_details", "available": True, "details": {"cases": [
        {"question": "Grounded question?", "answer": "Grounded response.", "reference_answer": "Reference.",
         "retrieved_contexts": ["Actual indexed source."], "should_refuse": False},
    ]}}]}

    result = run_rag_eval.run_ragas(run)

    assert set(result) == {"faithfulness", "context_precision", "context_recall", "answer_relevancy"}
    assert all(metric["value"] == 0.75 and metric["sample_size"] == 1 for metric in result.values())
    assert len(calls) == 4
    assert all(call[1]["retrieved_contexts"] == ["Actual indexed source."] for call in calls)
