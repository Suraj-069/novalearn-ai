"""Deterministic exam study plans based only on stored topic mastery estimates."""
from datetime import date, timedelta
from math import exp


def build_study_plan(topics: list[dict], *, today: date, exam_date: date, hours_per_day: float) -> dict:
    """Allocate 25-minute topic sessions; forgetting estimate is p*exp(-days/14).

    The 14-day time constant is a transparent planning heuristic, not a fitted
    memory model. Unassessed topics use the BKT initial prior (0.20).
    """
    if exam_date < today:
        raise ValueError("Exam date must be today or later.")
    if not 0.25 <= hours_per_day <= 16:
        raise ValueError("Hours per day must be between 0.25 and 16.")
    session_minutes = 25
    sessions_per_day = int(hours_per_day * 60 // session_minutes)
    if sessions_per_day < 1:
        raise ValueError("Available time must fit at least one 25-minute session.")
    days = (exam_date - today).days + 1
    plan = []
    for offset in range(days):
        day = today + timedelta(days=offset)
        ranked = []
        for topic in topics:
            mastery = topic.get("mastery")
            prior = 0.20 if mastery is None else max(0.0, min(1.0, float(mastery)))
            recall = prior * exp(-offset / 14)
            ranked.append((1 - recall, str(topic["name"]).casefold(), topic, recall, mastery is None))
        ranked.sort(key=lambda item: (-item[0], item[1], str(item[2]["id"])))
        # Preserve the weak-first ranking while rotating daily blocks through
        # other topics instead of assigning every day to only one topic.
        if ranked:
            shift = (offset * sessions_per_day) % len(ranked)
            ranked = ranked[shift:] + ranked[:shift]
        selected = ranked[:sessions_per_day]
        tasks = [{"topic_id": t["id"], "topic_name": t["name"], "minutes": session_minutes,
                  "estimated_recall": round(recall, 3),
                  "reason": "Not assessed; schedule a diagnostic or first practice." if unassessed
                           else f"Priority from estimated recall after {offset} day(s) of decay."}
                 for _, _, t, recall, unassessed in selected]
        plan.append({"date": day, "tasks": tasks})
    return {"exam_date": exam_date, "hours_per_day": hours_per_day, "formula": "estimated recall = current mastery estimate × exp(-days / 14); 25-minute sessions",
            "days": plan}
