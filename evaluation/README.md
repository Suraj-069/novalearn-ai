# Evaluation workflow

This folder has no human-reviewed benchmark answers or RAG evaluation scores. It may contain a timestamped synthetic personalization simulation report; that report exercises the service path using simulated learners and is not human learning evidence. NOVA Learn AI has no fixed course benchmark dataset, and the team must label test cases against its own uploaded material before interpreting a RAG evaluation run.

## Retrieval and grounded-answer cases

Create a JSON array in the course's **Evaluation** page. Use the source list on that page to find real chunks and copy their IDs. Answerable cases look like this:

```json
{
  "question": "A question whose answer is present in the selected course material",
  "reference_answer": "A human-checked answer grounded in that material",
  "relevant_chunk_ids": ["a-real-chunk-uuid-from-this-course"],
  "should_refuse": false
}
```

Off-material cases must have `reference_answer: null`, `relevant_chunk_ids: []`, and `should_refuse: true`. Do not assign a plausible source to a question the material does not cover. Each run accepts 1–50 cases. IDs from another course are rejected.

## Metrics

- `context_precision`: mean average precision over the retrieved top-k list using the supplied relevant chunk IDs as binary labels. A relevant chunk ranked first contributes more than one ranked lower.
- `context_recall`: relevant labeled chunk IDs retrieved divided by relevant labeled chunk IDs supplied. Off-material cases are excluded because they have no positive source labels.
- `faithfulness` and `answer_relevancy`: a single configured language model scores the tutor output against the retrieved evidence and question under an explicit rubric. This judge is not independent, and this implementation does not claim to be RAGAS, DeepEval, or TruLens. Scores are unavailable if no model is configured or valid scores are not returned.
- `refusal_accuracy`: exact agreement between the expected refusal label and whether the tutor returns its unsupported mode.
- `simulated_mastery_gain`: mean synthetic hidden-mastery change in the adaptive arm, not a BKT estimate and not real student learning.
- `random_baseline_mastery_gain` and `mastery_gain_delta`: synthetic hidden-mastery change under uniform-random topic selection and adaptive-minus-baseline difference.
- `adaptive_estimate_error` / `random_baseline_estimate_error`: absolute error between synthetic hidden mastery and app BKT estimates.
- `question_repetition_rate` / `baseline_repetition_rate`: repeated verified question IDs divided by presentations in each selection arm.
- Topic coverage and adaptive weak-topic selection rate are reported for both arms where applicable.

Every metric stores its sample size and either a computed value or an unavailable reason. The API simulation replays existing verified, topic-tagged questions, runs seeded synthetic response profiles through the production deterministic grader and BKT update, and does not write assessments, answers, or mastery events. It compares repeated runs. The CLI can write JSON, Markdown, and PNG artifacts from indexed course excerpts while using disposable SQLite for simulated writes. A simulated mastery change is not evidence of improved real-world learning; recommendation relevance and real learning outcomes are not established.

## API

- `GET /api/courses/{course_id}/evaluation-sources` lists paginated source chunks; use `q` to search their text.
- `POST /api/courses/{course_id}/evaluations/retrieval` accepts `{ "cases": [...] }`.
- `POST /api/courses/{course_id}/evaluations/personalization` accepts `sessions` (5+), `questions_per_session`, `runs` (2+), `seed`, and simulated `profiles` (`name`, `skill`, `slip`, `guess`, `learning`, `forgetting`).
- `GET /api/courses/{course_id}/evaluations` lists the latest runs for that course.
- `GET /api/evaluations/{run_id}` reads one run owned by the signed-in user.

All routes require bearer authentication. Course and run ownership is checked by the API.

## Optional RAGAS evaluation

Install the optional framework dependencies with `python -m pip install -r evaluation/requirements-ragas.txt`. Configure `LLM_PROVIDER=google`, `LLM_MODEL`, and `LLM_API_KEY` in the root `.env`. Run the normal approved-set workflow with `--ragas`:

```powershell
python evaluation/scripts/run_rag_eval.py --course-id <COURSE_UUID> --dataset evaluation/approved/<course>.jsonl --token <OWNER_ACCESS_TOKEN> --ragas
```

The runner evaluates answerable cases only, using the tutor response, retrieved source text, and human-reviewed reference answer returned by the application. It writes four framework metrics: RAGAS Context Precision, Context Recall, Faithfulness, and Answer Relevancy. The JSON/Markdown report keeps RAGAS results separate from the app's label-based metrics. If dependencies, Gemini access, actual responses, or retrieved contexts are unavailable, the report records RAGAS as unavailable; it does not substitute synthetic scores. No approved dataset or RAGAS report is bundled, so running this command against a real course is still required for measured RAG results.

RAGAS uses the modern metrics collections interface and Google's `google-genai` adapter. See the [RAGAS Gemini integration guide](https://docs.ragas.io/en/stable/howtos/integrations/gemini/) and [Context Precision metric reference](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/) for the adapter and metric definitions.
