"""Run approved JSONL cases through the application's real retrieval evaluator."""
import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_approved(path: Path) -> list[dict]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records or any(row.get("review_status") != "approved" for row in records):
        raise ValueError("Dataset must contain only approved records; no report was written.")
    if len(records) > 50:
        raise ValueError("The API accepts at most 50 cases per run.")
    cases = []
    for row in records:
        refuse = row["expected_behavior"] == "refuse"
        cases.append({"question": row["question"], "category": row["category"],
                      "reference_answer": None if refuse else row["reference_answer"],
                      "relevant_chunk_ids": [] if refuse else row["ground_truth_chunk_ids"], "should_refuse": refuse})
    return cases


def answerable_ragas_rows(run: dict) -> list[dict]:
    """Return only cases with a real tutor response, reference, and retrieved source text."""
    detail_metric = next((m for m in run.get("metrics", []) if m.get("name") == "case_details"), None)
    if not detail_metric or not detail_metric.get("available"):
        return []
    details = detail_metric.get("details", {}).get("cases", [])
    rows = []
    for case in details:
        if (case.get("should_refuse") or not case.get("answer") or not case.get("reference_answer")
                or not case.get("retrieved_contexts")):
            continue
        rows.append({"user_input": case["question"], "response": case["answer"],
                     "reference": case["reference_answer"], "retrieved_contexts": case["retrieved_contexts"]})
    return rows


def run_ragas(run: dict) -> dict:
    """Run RAGAS 0.4 collection metrics with the configured Google Gemini account."""
    from google import genai
    from ragas.embeddings import GoogleEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness

    from app.core.config import get_settings

    settings = get_settings()
    if settings.llm_provider not in {"google", "gemini"} or not settings.llm_api_key:
        raise RuntimeError("RAGAS requires the configured Google Gemini provider and LLM_API_KEY.")
    if not settings.llm_model:
        raise RuntimeError("RAGAS requires LLM_MODEL to be configured.")
    rows = answerable_ragas_rows(run)
    if not rows:
        raise RuntimeError("No answerable cases with tutor answers and retrieved source contexts are available.")
    client = genai.Client(api_key=settings.llm_api_key)
    llm = llm_factory(settings.llm_model, provider="google", client=client)
    embeddings = GoogleEmbeddings(client=client, model=settings.embedding_model or "gemini-embedding-001")
    metrics = {
        "faithfulness": Faithfulness(llm=llm),
        "context_precision": ContextPrecision(llm=llm),
        "context_recall": ContextRecall(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings),
    }
    async def score_all():
        output = {name: [] for name in metrics}
        for row in rows:
            args = {"user_input": row["user_input"], "response": row["response"],
                    "reference": row["reference"], "retrieved_contexts": row["retrieved_contexts"]}
            for name, metric in metrics.items():
                score = await metric.ascore(**args)
                output[name].append(float(score.value))
        return output

    values = asyncio.run(score_all())
    return {name: {"value": sum(scores) / len(scores), "sample_size": len(scores), "scores": scores}
            for name, scores in values.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[2] / "evaluation" / "reports")
    parser.add_argument("--api", default=os.environ.get("NOVA_API_URL", "http://localhost:8000/api"))
    parser.add_argument("--token", default=os.environ.get("NOVA_ACCESS_TOKEN"))
    parser.add_argument("--ragas", action="store_true", help="Also run the optional RAGAS framework metrics (Google Gemini required).")
    args = parser.parse_args()
    if not args.token:
        parser.error("Pass --token or set NOVA_ACCESS_TOKEN (a bearer token for the dataset's course owner).")
    cases = load_approved(args.dataset)
    payload = json.dumps({"cases": cases}).encode()
    request = urllib.request.Request(f"{args.api.rstrip('/')}/courses/{args.course_id}/evaluations/retrieval", data=payload,
                                     headers={"Authorization": f"Bearer {args.token}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            run = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Evaluation API returned HTTP {exc.code}; report not written.") from exc
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"rag-{stamp}.json"
    md_path = args.output_dir / f"rag-{stamp}.md"
    report = {"generated_at_utc": stamp, "dataset": str(args.dataset), "dataset_size": len(cases), "api": args.api,
              "run": run, "limitations": "Application metrics and optional RAGAS framework metrics are separate. RAGAS scores are model-based estimates, not human judgments."}
    if args.ragas:
        try:
            report["ragas"] = {"framework": "ragas", "version": "0.4.3", "metrics": run_ragas(run)}
        except Exception as exc:
            report["ragas"] = {"framework": "ragas", "version": "0.4.3", "available": False,
                                "error": f"{type(exc).__name__}: {exc}"}
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Retrieval evaluation report", "", f"- Run: `{run.get('id')}`", f"- UTC: {stamp}",
             f"- Approved test items: {len(cases)}", f"- Status: {run.get('status')}", "", "## Metrics", "",
             "| Metric | Value | Samples | Availability |", "|---|---:|---:|---|"]
    for metric in run.get("metrics", []):
        val = "not computed" if not metric.get("available") or metric.get("value") is None else f"{metric['value']:.4f}"
        lines.append(f"| {metric['name']} | {val} | {metric.get('sample_size', '')} | {metric.get('unavailable_reason') or 'available'} |")
    lines += ["", "## Limitations", "", report["limitations"], "", "The results reflect only the approved labels and this course/configuration. They do not establish learning gains."]
    if args.ragas:
        lines += ["", "## RAGAS framework metrics", ""]
        ragas_result = report["ragas"]
        if ragas_result.get("available") is False or "metrics" not in ragas_result:
            lines.append(f"RAGAS scores unavailable: {ragas_result.get('error', 'not computed')}")
        else:
            lines += ["| Metric | Mean | Samples |", "|---|---:|---:|"]
            for name, metric in ragas_result["metrics"].items():
                lines.append(f"| {name} | {metric['value']:.4f} | {metric['sample_size']} |")
            lines.append("These metrics were computed by RAGAS using Gemini; only answerable cases with an actual tutor response and retrieved contexts are included.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved run {run.get('id')} to {json_path} and {md_path}")


if __name__ == "__main__":
    main()
