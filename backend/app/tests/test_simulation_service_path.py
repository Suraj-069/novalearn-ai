"""The synthetic learner experiment uses the app's real assessment and mastery services."""
from app.services.assessment import service
from app.services.evaluation.simulation import simulate_service_path


MATERIAL = {
    "Energy": [
        "Thermodynamics studies energy transfer between systems. Heat moves because of temperature differences, while work transfers energy through organized forces.",
        "Internal energy includes microscopic kinetic and potential energy stored throughout a material system. Conservation connects heat, work, and internal change.",
        "Entropy describes how energy spreads among possible microscopic arrangements. Isolated systems tend toward greater entropy during spontaneous physical processes.",
    ],
    "Engines": [
        "A heat engine absorbs energy from a hot reservoir and converts part of that energy into useful mechanical work during each cycle.",
        "Carnot efficiency depends on the temperatures of hot and cold reservoirs. No engine operating between those reservoirs can exceed this limit.",
        "Refrigerators use external work to move heat from a cold space toward warmer surroundings, against the natural direction of heat transfer.",
    ],
}


def test_simulation_runs_through_real_assessment_and_submission_services(monkeypatch):
    calls = {"create": 0, "submit": 0}
    create = service.create_assessment
    submit = service.submit_attempt

    def create_spy(db, **kwargs):
        calls["create"] += 1
        assert db.get_bind().dialect.name == "sqlite"
        return create(db, **kwargs)

    def submit_spy(db, *args, **kwargs):
        calls["submit"] += 1
        assert db.get_bind().dialect.name == "sqlite"
        return submit(db, *args, **kwargs)

    monkeypatch.setattr(service, "create_assessment", create_spy)
    monkeypatch.setattr(service, "submit_attempt", submit_spy)
    profiles = ({"name": "test", "skill": .55, "slip": .15, "guess": .2,
                 "learning": .1, "forgetting": .01},)

    result = simulate_service_path(MATERIAL, sessions=5, questions_per_session=1, runs=2,
                                   profiles=profiles, seed=1337)

    assert result["available"] is True, result
    assert result["synthetic_only"] is True
    assert result["service_path"] == ["create_assessment", "start_attempt", "submit_attempt", "grade_answer", "record_answer", "BKT update"]
    assert result["repeat_count"] == 2
    assert calls["create"] == calls["submit"] == 20  # one per arm, run, profile, and session
    assert result["evidence"]["assessments_created"] == 20
    assert result["evidence"]["attempts_submitted"] == 20
    assert result["evidence"]["graded_answers"] == 20
    assert result["evidence"]["mastery_events"] == 20
    assert len(result["trajectories"]) == 4
    assert all(len(row["sessions"]) == 5 for row in result["trajectories"])
    assert all(
        abs(row["sessions"][-1]["synthetic_mastery_gain"] -
            (row["sessions"][-1]["synthetic_true_mastery"] - row["initial_synthetic_true_mastery"])) < 1e-12
        for row in result["trajectories"]
    )
    for arm in ("random", "adaptive"):
        rows = [row for row in result["trajectories"] if row["arm"] == arm]
        expected_gain = sum(row["sessions"][-1]["synthetic_mastery_gain"] for row in rows) / len(rows)
        assert abs(result["arms"][arm]["synthetic_mastery_gain_mean"] - expected_gain) < 1e-12
    assert all("question_repetition_rate" in row and "topic_coverage" in row for row in result["trajectories"])
    assert all("recommendation_weak_topic_precision" in row and "recommendation_count" in row
               for row in result["trajectories"])
    assert all("final_absolute_estimate_error" in row for row in result["trajectories"])
    assert all(0 <= result["arms"][arm]["recommendation_weak_topic_precision_mean"] <= 1
               for arm in ("random", "adaptive"))


def test_simulation_requires_explicit_synthetic_source_material():
    result = simulate_service_path({}, sessions=1, profiles=())
    assert result == {"available": False, "reason": "Synthetic source material is required."}
