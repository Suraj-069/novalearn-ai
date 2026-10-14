"""Focused checks for honest report inputs and synthetic metric presentation."""
from types import SimpleNamespace

from scripts.run_simulation import _chart, _course_metadata, _markdown_report, _topic_material


def test_report_input_uses_topic_tagged_source_excerpts_and_skips_generated_descriptions():
    chunks = [
        SimpleNamespace(topic_id="t1", text="Real indexed course excerpt.", is_generated_description=False),
        SimpleNamespace(topic_id="t1", text="Generated caption.", is_generated_description=True),
        SimpleNamespace(topic_id="missing", text="Untyped excerpt.", is_generated_description=False),
        SimpleNamespace(topic_id="t2", text="   ", is_generated_description=False),
    ]

    material = _topic_material(chunks, {"t1": "Energy", "t2": "Engines"})

    assert material == {"Energy": ["Real indexed course excerpt."]}


def test_course_report_metadata_is_copied_before_session_close():
    class FakeCourse:
        id = "course-id"
        title = "Course title"

    course_id, title = _course_metadata(FakeCourse())
    assert (course_id, title) == ("course-id", "Course title")


def test_report_discloses_required_metrics_and_marks_unavailable_metrics(tmp_path):
    payload = {
        "created_at": "2026-10-14T00:00:00+00:00",
        "course_id": "course-1",
        "course_title": "Thermodynamics",
        "source_excerpt_count": 12,
        "runs": 5,
        "seed": 7,
        "result": {
            "sessions": 5,
            "questions_per_session": 1,
            "repeat_count": 5,
            "topic_count": 2,
            "service_path": ["create_assessment", "submit_attempt", "BKT update"],
            "evidence": {"assessments_created": 10, "attempts_submitted": 10,
                         "graded_answers": 10, "mastery_events": 10},
            "arms": {
                "random": {"synthetic_mastery_gain_mean": .1, "synthetic_mastery_gain_stddev": .02,
                           "recommendation_weak_topic_precision_mean": .4, "recommendation_weak_topic_precision_stddev": .1,
                           "final_estimate_error_mean": .03, "final_estimate_error_stddev": .01,
                           "final_absolute_estimate_error_mean": .12, "final_absolute_estimate_error_stddev": .03,
                           "question_repetition_rate_mean": .1, "question_repetition_rate_stddev": .02,
                           "topic_coverage_mean": .5, "topic_coverage_stddev": .1, "sample_size": 5},
                "adaptive": {"synthetic_mastery_gain_mean": .2, "synthetic_mastery_gain_stddev": .04,
                             "recommendation_weak_topic_precision_mean": .8, "recommendation_weak_topic_precision_stddev": .05,
                             "final_estimate_error_mean": -.02, "final_estimate_error_stddev": .01,
                             "final_absolute_estimate_error_mean": .08, "final_absolute_estimate_error_stddev": .02,
                             "question_repetition_rate_mean": None, "question_repetition_rate_stddev": None,
                             "topic_coverage_mean": .75, "topic_coverage_stddev": .05, "sample_size": 5},
            },
            "trajectories": [
                {"arm": arm, "sessions": [{"synthetic_true_mastery": value} for value in (.4, .42, .45, .48, .5)]}
                for arm in ("random", "adaptive")
            ],
        },
    }
    png_path = tmp_path / "trajectory.png"

    report = _markdown_report(payload, png_path)
    _chart(payload["result"], png_path)

    assert "Question repetition rate" in report
    assert "Topic coverage" in report
    assert "Mean absolute BKT error" in report
    assert "Recommendation weak-topic precision" in report
    assert "Signed BKT bias" in report
    assert "0.1000 ± 0.0200" in report
    assert "0.4000 ± 0.1000" in report
    assert "Unavailable" in report
    assert "No simulation rows are written to the configured user database" in report
    assert "not observations of students" in report
    assert png_path.is_file() and png_path.stat().st_size > 0
