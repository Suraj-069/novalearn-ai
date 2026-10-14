"""Write a synthetic adaptive-vs-random report from one course's indexed source excerpts.

Run from backend/: python scripts/run_simulation.py --course-id UUID
Simulation writes occur only in a disposable in-memory SQLite database.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image, ImageDraw  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database.session import SessionLocal  # noqa: E402
from app.models.course import Course  # noqa: E402
from app.models.knowledge import ContentChunk, Topic  # noqa: E402
from app.services.evaluation.simulation import PROFILES, simulate_service_path  # noqa: E402


def _course_metadata(course) -> tuple[object, str]:
    """Copy fields needed by the report before the database session is closed."""
    return course.id, course.title


def _topic_material(chunks, topics: dict) -> dict[str, list[str]]:
    """Return source excerpts grouped by course topic, excluding generated descriptions."""
    names = {topic_id: name for topic_id, name in topics.items()}
    material: dict[str, list[str]] = {}
    for chunk in chunks:
        if chunk.topic_id not in names or chunk.is_generated_description:
            continue
        text = (chunk.text or "").strip()
        if text:
            material.setdefault(names[chunk.topic_id], []).append(text)
    return material


def _session_series(result: dict, arm: str, field: str) -> list[float]:
    rows = [row for row in result.get("trajectories", []) if row.get("arm") == arm]
    count = result.get("sessions", 0)
    if not rows or not count:
        return []
    return [sum(row["sessions"][index][field] for row in rows) / len(rows) for index in range(count)]


def _chart(result: dict, target: Path) -> None:
    width, height = 960, 520
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 84, 56, 900, 430
    draw.text((left, 18), "Synthetic hidden mastery by session (mean simulated learners)", fill="#172554")
    draw.line((left, top, left, bottom, right, bottom), fill="#64748b", width=2)
    colors = {"random": "#64748b", "adaptive": "#4f46e5"}
    for fraction in (0, .25, .5, .75, 1):
        y = round(bottom - fraction * (bottom - top))
        draw.line((left, y, right, y), fill="#e2e8f0")
        draw.text((34, y - 7), f"{fraction:.0%}", fill="#475569")
    for arm, color in colors.items():
        values = _session_series(result, arm, "synthetic_true_mastery")
        points = []
        for i, value in enumerate(values):
            x = left + round((right - left) * i / max(1, len(values) - 1))
            y = round(bottom - value * (bottom - top))
            points.append((x, y))
            draw.text((x - 9, bottom + 12), str(i + 1), fill="#475569")
        if len(points) > 1:
            draw.line(points, fill=color, width=4)
        for point in points:
            x, y = point
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)
    draw.text((left, bottom + 42), "Session", fill="#475569")
    draw.line((right - 190, 26, right - 160, 26), fill=colors["random"], width=4)
    draw.text((right - 152, 19), "Random baseline", fill="#334155")
    draw.line((right - 190, 46, right - 160, 46), fill=colors["adaptive"], width=4)
    draw.text((right - 152, 39), "Adaptive", fill="#334155")
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")


def _show_metric(value) -> str:
    return "Unavailable" if value is None else f"{value:.4f}"


def _show_summary(metrics: dict, key: str) -> str:
    value, spread = metrics.get(f"{key}_mean"), metrics.get(f"{key}_stddev")
    if value is None or spread is None:
        return "Unavailable"
    return f"{value:.4f} ± {spread:.4f}"


def _markdown_report(payload: dict, png_path: Path) -> str:
    result = payload["result"]
    lines = [
        f"# Synthetic personalization simulation — {payload['course_title']}", "",
        f"Run date (UTC): {payload['created_at']}", f"Course ID: `{payload['course_id']}`",
        f"Source excerpts read from the course: {payload['source_excerpt_count']} across {result.get('topic_count', 0)} topics",
        f"Protocol: {result.get('sessions', 'Unavailable')} sessions × {result.get('questions_per_session', 'Unavailable')} questions × {len(PROFILES)} profiles × {result.get('repeat_count', 'Unavailable')} repeated runs",
        f"Seed: `{payload['seed']}`", "", "## Adaptive service path vs random baseline", "",
        "| Arm | Synthetic hidden-mastery gain (mean ± SD) | Signed BKT bias (mean ± SD) | Mean absolute BKT error (mean ± SD) | Question repetition rate (mean ± SD) | Topic coverage (mean ± SD) | Recommendation weak-topic precision (mean ± SD) | Learners |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, label in (("random", "Random baseline"), ("adaptive", "Adaptive")):
        metrics = result.get("arms", {}).get(arm, {})
        lines.append("| " + label + " | " + " | ".join((
            _show_summary(metrics, "synthetic_mastery_gain"),
            _show_summary(metrics, "final_estimate_error"),
            _show_summary(metrics, "final_absolute_estimate_error"),
            _show_summary(metrics, "question_repetition_rate"),
            _show_summary(metrics, "topic_coverage"),
            _show_summary(metrics, "recommendation_weak_topic_precision"),
            str(metrics.get("sample_size", "Unavailable")),
        )) + " |")
    lines += ["", "### Reported metric definitions", "",
              "Question repetition rate counts previously presented normalized question text for the same simulated learner. Topic coverage is the share of course topics practiced at least once. BKT error compares production mastery estimates with the simulator's hidden synthetic mastery; positive signed error means the estimate is higher. Recommendation weak-topic precision is the share of service-generated open recommendations (excluding diagnostic assess_topic items) aimed at topics whose synthetic hidden mastery is below 0.40; it is synthetic-only and unavailable when there were no eligible recommendations.",
              "", "## Service evidence", "",
              "Production path exercised in the disposable database: " + " → ".join(result.get("service_path", [])) + ".",
              f"Created assessments: {result.get('evidence', {}).get('assessments_created', 'Unavailable')}; submitted attempts: {result.get('evidence', {}).get('attempts_submitted', 'Unavailable')}; graded answers: {result.get('evidence', {}).get('graded_answers', 'Unavailable')}; BKT mastery events: {result.get('evidence', {}).get('mastery_events', 'Unavailable')}.",
              "", f"![Synthetic hidden mastery trajectories]({png_path.name})", "",
              "## Method and limits", "",
              "The runner reads indexed source excerpts and topic labels from the selected course. It copies those excerpts into an isolated in-memory SQLite database, where the app's real assessment creation and verification, attempt, grading, recommendation, and BKT update services run. No simulation rows are written to the configured user database. Simulated responses follow profile-specific hidden skill, slip, guess, learning, and forgetting parameters.",
              "", "These are synthetic outcomes, not observations of students or evidence of real learning gains. BKT parameters remain fixed and are not fitted. Tutor conversation quality and recommendation relevance are not measured by this simulation.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--runs", type=int, default=5, choices=range(2, 21))
    parser.add_argument("--sessions", type=int, default=5, choices=range(5, 13))
    parser.add_argument("--questions-per-session", type=int, default=1, choices=range(1, 21))
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation" / "reports")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        course = db.get(Course, args.course_id)
        if course is None:
            print("[FAIL] Course not found in the configured database.")
            return 1
        course_id, course_title = _course_metadata(course)
        topics = dict(db.execute(select(Topic.id, Topic.name).where(Topic.course_id == course_id)).all())
        chunks = list(db.scalars(select(ContentChunk).where(ContentChunk.course_id == course_id,
                                                             ContentChunk.topic_id.is_not(None),
                                                             ContentChunk.is_generated_description.is_(False))
                                 .order_by(ContentChunk.document_id, ContentChunk.chunk_index)).all())
        material = _topic_material(chunks, topics)
        if not material:
            print("[FAIL] No topic-tagged source excerpts are available. No report was written.")
            return 1
        db.rollback()
        db.close()
        result = simulate_service_path(material, sessions=args.sessions,
                                       questions_per_session=args.questions_per_session,
                                       runs=args.runs, seed=args.seed, profiles=PROFILES)
        if not result.get("available"):
            print(f"[FAIL] {result.get('reason')} No report was written.")
            return 1

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        prefix = args.output / f"simulation-{stamp}"
        prefix.parent.mkdir(parents=True, exist_ok=True)
        json_path, md_path, png_path = (prefix.with_suffix(suffix) for suffix in (".json", ".md", ".png"))
        payload = {"created_at": datetime.now(timezone.utc).isoformat(), "course_id": str(course_id),
                   "course_title": course_title, "source_excerpt_count": sum(map(len, material.values())),
                   "runs": args.runs, "seed": args.seed, "method": "synthetic learner answers through production assessment creation, attempt, grading and BKT services in disposable SQLite; uniform random-topic selection versus production mastery-weighted adaptive assessment creation",
                   "result": result}
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _chart(result, png_path)
        md_path.write_text(_markdown_report(payload, png_path), encoding="utf-8")
        print(f"[PASS] Wrote synthetic service-path simulation outputs for {payload['source_excerpt_count']} source excerpts:")
        print(f"JSON: {json_path}\nMarkdown: {md_path}\nPNG: {png_path}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
