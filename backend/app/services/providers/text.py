"""Shared text utilities: tokenisation, light stemming, stop-words."""
import re

STOPWORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has have how i if in into is it its of on or "
    "our so such than that the their then there these they this to was we were what when where which who why will with "
    "would you your about explain tell me us give show describe define difference between mean means meant".split()
)
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def stem(w: str) -> str:
    """Very light suffix stripping so 'cycles'/'cycle' and 'heating'/'heat' match. Not a real stemmer."""
    for suf in ("ingly", "edly", "ing", "ies", "ed", "es", "s", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokens(text: str, *, drop_stop: bool = True) -> list[str]:
    out = []
    for t in _TOKEN.findall(text.lower()):
        if drop_stop and t in STOPWORDS:
            continue
        out.append(stem(t))
    return out
