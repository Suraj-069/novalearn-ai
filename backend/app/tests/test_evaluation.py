import uuid

from sqlalchemy import func, select

from app.api import evaluation as evaluation_api
from app.models.assessment import Question
from app.models.course import Document
from app.models.evaluation import EvaluationRun
from app.models.knowledge import ContentChunk, Topic
from app.models.learner import TopicMasteryHistory
from app.services.providers.embeddings import LocalHashEmbedding
from scripts.run_simulation import _chart


def _metric_map(run):
    return {metric["name"]: metric for metric in run["metrics"]}


def test_source_list_and_retrieval_run_use_real_course_chunks(monkeypatch, client, alice, bob, thermo, db):
    monkeypatch.setattr(evaluation_api, "get_embedding_provider", lambda: LocalHashEmbedding(768))
    monkeypatch.setattr(evaluation_api, "get_llm", lambda: None)
    cid = thermo["course"]["id"]
    chunk = db.scalars(select(ContentChunk).where(ContentChunk.course_id == uuid.UUID(cid),
                                                   ContentChunk.text.ilike("%first law of thermodynamics%"))).first()
    assert chunk is not None

    source_list = client.get(f"/api/courses/{cid}/evaluation-sources?q=first%20law", headers=alice)
    assert source_list.status_code == 200
    assert any(item["chunk_id"] == str(chunk.id) for item in source_list.json()["items"])

    response = client.post(f"/api/courses/{cid}/evaluations/retrieval", headers=alice, json={"cases": [
        {"question": "What does the first law of thermodynamics say about energy?",
         "reference_answer": "Energy is conserved.", "relevant_chunk_ids": [str(chunk.id)], "should_refuse": False},
        {"question": "Who won yesterday's international chess tournament?",
         "reference_answer": None, "relevant_chunk_ids": [], "should_refuse": True},
    ]})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "completed"
    assert "answer_model" in run["config"] and "judge_model" in run["config"]
    metrics = _metric_map(run)
    assert metrics["context_precision"]["available"] is True
    assert metrics["context_recall"]["value"] == 1.0
    assert metrics["evaluated_cases"]["value"] == 2.0
    assert metrics["faithfulness"]["available"] is False
    assert metrics["faithfulness"]["value"] is None
    assert metrics["faithfulness"]["unavailable_reason"]
    assert metrics["answer_relevancy"]["available"] is False
    assert metrics["refusal_accuracy"]["sample_size"] == 2
    assert metrics["false_refusal_rate"]["sample_size"] == 1
    assert metrics["false_acceptance_rate"]["sample_size"] == 1
    assert metrics["hit_at_k"]["value"] == 1.0
    assert metrics["mrr"]["available"] is True
    assert metrics["citation_accuracy"]["available"] is True
    details = metrics["case_details"]["details"]["cases"]
    assert details[0]["retrieved_contexts"]
    assert details[0]["retrieved_contexts"][0]
    assert details[0]["retrieved_sources"]
    assert details[0]["retrieved_sources"][0]["chunk_id"] in details[0]["retrieved_chunk_ids"]
    assert details[0]["retrieved_sources"][0]["filename"]
    assert details[0]["retrieved_sources"][0]["excerpt"] == details[0]["retrieved_contexts"][0][:500]

    run_id = run["id"]
    assert client.get(f"/api/evaluations/{run_id}", headers=alice).status_code == 200
    assert client.get(f"/api/evaluations/{run_id}", headers=bob).status_code == 404
    assert client.get(f"/api/courses/{cid}/evaluations", headers=bob).status_code == 404


def test_retrieval_labels_reject_cross_course_chunk(monkeypatch, client, alice, course, db):
    other = client.post("/api/courses", headers=alice, json={"title": "Other course"}).json()
    document = Document(course_id=uuid.UUID(other["id"]), original_filename="other.txt", stored_path="missing",
                        source_type="transcript", mime_type="text/plain", size_bytes=1, sha256="0" * 64)
    db.add(document)
    db.flush()
    chunk = ContentChunk(course_id=uuid.UUID(other["id"]), document_id=document.id, chunk_index=0,
                         source_type="transcript", text="A labeled passage belonging to a different course.")
    db.add(chunk)
    db.commit()
    response = client.post(f"/api/courses/{course['id']}/evaluations/retrieval", headers=alice, json={"cases": [
        {"question": "What does another course say?", "reference_answer": "A reference.",
         "relevant_chunk_ids": [str(chunk.id)], "should_refuse": False},
    ]})
    assert response.status_code == 422
    assert "belong to this course" in response.json()["detail"]
    assert db.scalar(select(func.count()).select_from(EvaluationRun)) == 0


def test_personalization_simulation_compares_arms_deterministically_and_writes_chart(client, alice, thermo, db, tmp_path):
    cid = uuid.UUID(thermo["course"]["id"])
    topic = db.scalars(select(Topic).where(Topic.course_id == cid)).first()
    assert topic is not None
    for n in range(2):
        db.add(Question(course_id=cid, topic_id=topic.id, subtopic_id=None,
                        text=f"How does the verified test question {n} describe energy?", normalized_text=f"test question {n}",
                        question_type="mcq", difficulty="easy", options=[], answer_key={"correct": "a"},
                        explanation="Test fixture question.", verification_status="verified", verification={}))
    db.commit()
    history_before = db.scalar(select(func.count()).select_from(TopicMasteryHistory))

    payload = {
        "sessions": 5, "questions_per_session": 2, "runs": 3, "seed": 23,
        "profiles": [{"name": "Test profile", "skill": 0.7}],
    }
    response = client.post(f"/api/courses/{cid}/evaluations/personalization", headers=alice, json=payload)
    assert response.status_code == 201, response.text
    run = response.json()
    metrics = _metric_map(run)
    assert run["status"] == "completed"
    assert metrics["simulated_mastery_gain"]["available"] is True
    assert metrics["simulated_mastery_gain"]["sample_size"] == 3
    assert metrics["random_baseline_mastery_gain"]["available"] is True
    assert metrics["mastery_gain_delta"]["available"] is True
    assert metrics["simulated_mastery_gain"]["details"]["arms"]["adaptive"]["sample_size"] == 3
    assert metrics["simulated_mastery_gain"]["details"]["arms"]["random"]["sample_size"] == 3
    assert 0 <= metrics["question_repetition_rate"]["value"] <= 1
    assert metrics["question_repetition_rate"]["details"]["repeat_count"] == 3
    details = metrics["simulated_mastery_gain"]["details"]
    image = tmp_path / "simulation.png"
    _chart(details, image)
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    repeat = client.post(f"/api/courses/{cid}/evaluations/personalization", headers=alice, json=payload)
    assert repeat.status_code == 201, repeat.text
    assert _metric_map(repeat.json())["simulated_mastery_gain"]["details"]["arms"] == details["arms"]
    assert db.scalar(select(func.count()).select_from(TopicMasteryHistory)) == history_before


def test_personalization_metrics_are_unavailable_without_a_verified_question_bank(client, alice, course):
    response = client.post(f"/api/courses/{course['id']}/evaluations/personalization", headers=alice, json={})
    assert response.status_code == 201, response.text
    run = response.json()
    metrics = _metric_map(run)
    assert run["status"] == "completed"
    for name in ("simulated_mastery_gain", "question_repetition_rate"):
        assert metrics[name]["available"] is False
        assert metrics[name]["value"] is None
        assert "No verified" in metrics[name]["unavailable_reason"]
