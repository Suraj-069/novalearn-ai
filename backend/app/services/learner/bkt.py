"""Bayesian Knowledge Tracing, kept deliberately small and transparent.

Each topic has a hidden state "knows it / doesn't". After each graded answer we update the probability of
"knows it" with Bayes' rule, then allow for learning. All parameters are plain constants (not fitted to data),
so the output is an *estimate*, never a measurement. The model never sees or depends on any LLM output.
"""
P_INIT = 0.20   # prior for a topic with no evidence: we do not assume the student already knows the material
P_LEARN = 0.10  # chance of learning the topic between two questions
SLIP = {"easy": 0.10, "medium": 0.15, "hard": 0.20}                 # knows it but answers wrongly
GUESS = {"mcq": 0.25, "numerical": 0.05, "short_answer": 0.15}     # doesn't know it but answers rightly
LOW, HIGH = 0.02, 0.98  # never fully certain either way
# These constants are deliberately conservative and are NOT fitted to data. Early estimates (few answers) are volatile;
# the UI therefore shows how many answers each estimate rests on.


def update(p: float, score: float, qtype: str, difficulty: str) -> tuple[float, dict]:
    """Return (new mastery, parameters used). `score` in [0,1]; partial credit blends the two outcomes."""
    s, g = SLIP[difficulty], GUESS[qtype]
    p_if_correct = p * (1 - s) / (p * (1 - s) + (1 - p) * g)
    p_if_wrong = p * s / (p * s + (1 - p) * (1 - g))
    posterior = score * p_if_correct + (1 - score) * p_if_wrong
    new = min(HIGH, max(LOW, posterior + (1 - posterior) * P_LEARN))
    return new, {"slip": s, "guess": g, "learn": P_LEARN, "posterior": round(posterior, 4)}
