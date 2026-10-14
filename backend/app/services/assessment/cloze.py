"""Offline question generation: fill-in-the-blank questions built from a sentence of the course material.

The correct answer is, by construction, a word that appears in the source sentence, so it can be verified
against the evidence without any language model. Difficulty is a transparent format ladder:
  easy   = multiple choice (recognise the term among 4 options)
  medium = short answer, one blank (recall the term)
  hard   = short answer, two blanks in one sentence (recall two concepts)
It does NOT measure how conceptually deep a question is; a language model is needed for that.
"""
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from app.models.knowledge import ContentChunk
from app.services.assessment.common import Candidate
from app.services.providers.text import STOPWORDS, stem, tokens

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[A-Za-z][A-Za-z\-]{4,}")
SKIP_PREFIX = ("speaker notes", "key terms", "ai description", "body for")
MAX_DF_SHARE = 0.6


@dataclass
class Vocab:
    n: int
    df: Counter                       # stem -> number of chunks containing it
    surface: dict[str, str]           # stem -> most common surface form
    topics: dict[str, set]            # stem -> topic ids it appears in


def build_vocab(chunks: list[ContentChunk]) -> Vocab:
    df: Counter = Counter()
    forms: dict[str, Counter] = defaultdict(Counter)
    topics: dict[str, set] = defaultdict(set)
    for c in chunks:
        seen = set()
        for w in _WORD.findall(c.text):
            lw = w.lower()
            if lw in STOPWORDS:
                continue
            st = stem(lw)
            forms[st][lw if not w[0].isupper() else w] += 1
            seen.add(st)
        for st in seen:
            df[st] += 1
            topics[st].add(c.topic_id)
    return Vocab(len(chunks), df, {s: f.most_common(1)[0][0] for s, f in forms.items()}, topics)


def alpha_ratio(s: str) -> float:
    return sum(ch.isalpha() or ch.isspace() for ch in s) / max(1, len(s))


def candidate_sentences(text: str) -> list[str]:
    out = []
    for s in (x.strip() for x in _SENT.split(text)):
        words = s.split()
        if 8 <= len(words) <= 40 and alpha_ratio(s) >= 0.8 and "|" not in s and not s.lower().startswith(SKIP_PREFIX):
            out.append(s)
    return out


def _terms(sentence: str, v: Vocab) -> list[tuple[float, str, str]]:
    """Blankable terms: (score, surface, stem), best first. A term must occur exactly once in the sentence."""
    stems = Counter(tokens(sentence))
    found = []
    for m in _WORD.finditer(sentence):
        w = m.group(0)
        lw = w.lower()
        st = stem(lw)
        if lw in STOPWORDS or stems[st] != 1 or v.df[st] == 0:
            continue
        if v.n >= 5 and v.df[st] / v.n > MAX_DF_SHARE:
            continue
        score = math.log((v.n + 1) / v.df[st]) + (0.6 if w[0].isupper() and m.start() > 0 else 0) + 0.02 * len(w)
        found.append((score, w, st))
    return sorted(found, key=lambda t: (-t[0], t[1]))


def _blank(sentence: str, surface: str, marker: str = "_____") -> str:
    return re.sub(rf"\b{re.escape(surface)}\b", marker, sentence, count=1)


def _distractors(answer_stem: str, answer_surface: str, chunk: ContentChunk, v: Vocab, topic_names: dict, rng: random.Random):
    chunk_stems = set(tokens(chunk.text, drop_stop=False))
    pool = []
    for st, df in v.df.items():
        sf = v.surface[st]
        if st == answer_stem or st in chunk_stems or len(sf) < 5 or sf.lower() in STOPWORDS:
            continue
        if v.n >= 5 and df / v.n > MAX_DF_SHARE:
            continue
        other = any(t != chunk.topic_id for t in v.topics[st])
        pool.append((other * 1.0 - abs(len(sf) - len(answer_surface)) * 0.1 + rng.random() * 0.5, st, sf))
    pool.sort(key=lambda t: (-t[0], t[2]))
    out = []
    for _, st, sf in pool[:3]:
        sf = sf.capitalize() if answer_surface[0].isupper() else sf.lower()
        tid = next((t for t in v.topics[st] if t != chunk.topic_id), None) or next(iter(v.topics[st]), None)
        out.append({"text": sf, "from_topic": topic_names.get(tid)})
    return out if len(out) == 3 else None


def make_candidates(chunk: ContentChunk, v: Vocab, topic_names: dict, qtype: str, difficulty: str, rng: random.Random, limit: int = 3) -> list[Candidate]:
    """Up to `limit` candidates for one chunk and one (type, difficulty)."""
    out: list[Candidate] = []
    sentences = candidate_sentences(chunk.text)
    rng.shuffle(sentences)
    for sent in sentences:
        terms = _terms(sent, v)
        need = 2 if (qtype == "short_answer" and difficulty == "hard") else 1
        if len(terms) < need:
            continue
        explanation = f"The source states: \u201c{sent}\u201d"
        base = dict(chunk_id=chunk.id, topic_id=chunk.topic_id, subtopic_id=chunk.subtopic_id, method="cloze", explanation=explanation, source_text=chunk.text)
        if qtype == "mcq":
            _, surf, st = terms[0]
            d = _distractors(st, surf, chunk, v, topic_names, rng)
            if not d:
                continue
            opts = [{"text": surf, "from_topic": None, "_correct": True}] + [dict(x, _correct=False) for x in d]
            rng.shuffle(opts)
            options, correct = [], None
            for i, o in enumerate(opts):
                oid = "abcd"[i]
                options.append({"id": oid, "text": o["text"], "from_topic": o["from_topic"]})
                if o["_correct"]:
                    correct = oid
            out.append(Candidate(text=f"Which term best completes this statement from your course material?\n\n\u201c{_blank(sent, surf)}\u201d",
                                 qtype="mcq", difficulty="easy", answer_key={"correct": correct}, options=options, **base))
        elif qtype == "short_answer":
            picked = terms[:need]
            blanked = sent
            for i, (_, surf, _) in enumerate(picked, start=1):
                blanked = _blank(blanked, surf, "_____" if need == 1 else f"_____({i})")
            concepts = [{"name": surf, "accepted": [surf]} for _, surf, _ in picked]
            prompt = "Fill in the blank" if need == 1 else "Fill in the two blanks (in either order)"
            out.append(Candidate(text=f"{prompt}:\n\n\u201c{blanked}\u201d", qtype="short_answer", difficulty="medium" if need == 1 else "hard",
                                 answer_key={"answers": [c["name"] for c in concepts]}, rubric={"concepts": concepts, "partial_credit": True}, **base))
        if len(out) >= limit:
            break
    return out
