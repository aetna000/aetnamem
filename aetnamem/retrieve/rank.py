"""General-purpose recall ranking.

Recall has top-k semantics: a bounded set of the subject's *active* records
is scored by text relevance + trust + recency and the best `limit` are
returned. There is no query-specific keyword table; when nothing matches
lexically the trust/recency prior still surfaces recent, reliable candidates.
Retrieval events retain a bounded score sample.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

TEXT_WEIGHT = 0.75
TRUST_WEIGHT = 0.15
RECENCY_WEIGHT = 0.10

_TRUST_SCORES = {
    "trusted_user": 1.0,
    "user_confirmed": 0.9,
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """
    a about after all am an and any are as at be been before but by can could
    did do does for from had has have he her his how i if in is it its me my
    no not of on or our should so that the their them then there they this to
    up us was we were what when where which who why will with would you your
    """.split()
)


@dataclass(frozen=True)
class ScoredRecord:
    record: dict[str, Any]
    score: float
    text_score: float
    trust_score: float
    recency_score: float


def query_tokens(query: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(query.lower())
        if token not in _STOPWORDS
    ]


def token_overlap_components(query: str, content: str) -> tuple[int, int]:
    """Return matched and total normalized query terms for fallback scoring."""
    query_stems = {_stem(token) for token in query_tokens(query)}
    content_stems = {_stem(token) for token in _TOKEN_RE.findall(content.lower())}
    return len(query_stems & content_stems), len(query_stems)


def rank_records(
    query: str,
    records: list[dict[str, Any]],
    *,
    fts_scores: dict[str, float] | None = None,
) -> list[ScoredRecord]:
    """Score every candidate record against the query, best first.

    `fts_scores` are raw relevance scores from the store's full-text index
    (higher is better). When absent, a token-overlap fallback with light
    stemming is used so behavior degrades gracefully without FTS5.
    """
    if not records:
        return []

    tokens = query_tokens(query)
    if fts_scores is not None:
        max_raw = max(fts_scores.values(), default=0.0)
        text_scores = {
            record_id: (raw / max_raw if max_raw > 0 else 0.0)
            for record_id, raw in fts_scores.items()
        }
    else:
        text_scores = {
            str(record.get("id")): _overlap_score(tokens, str(record.get("content") or ""))
            for record in records
        }

    by_recency = sorted(
        records,
        key=lambda record: (str(record.get("created_at") or ""), str(record.get("id"))),
    )
    recency_rank = {
        str(record.get("id")): index for index, record in enumerate(by_recency)
    }
    recency_denominator = max(len(records) - 1, 1)

    scored: list[ScoredRecord] = []
    for record in records:
        record_id = str(record.get("id"))
        text_score = text_scores.get(record_id, 0.0)
        trust_score = _TRUST_SCORES.get(str(record.get("trust_tier")), 0.4)
        recency_score = recency_rank[record_id] / recency_denominator
        score = (
            TEXT_WEIGHT * text_score
            + TRUST_WEIGHT * trust_score
            + RECENCY_WEIGHT * recency_score
        )
        scored.append(
            ScoredRecord(
                record=record,
                score=round(score, 6),
                text_score=round(text_score, 6),
                trust_score=round(trust_score, 6),
                recency_score=round(recency_score, 6),
            )
        )

    scored.sort(
        key=lambda item: (
            -item.score,
            str(item.record.get("created_at") or ""),
            str(item.record.get("id")),
        )
    )
    return scored


def _overlap_score(tokens: list[str], content: str) -> float:
    if not tokens:
        return 0.0
    query_stems = {_stem(token) for token in tokens}
    content_stems = {_stem(token) for token in _TOKEN_RE.findall(content.lower())}
    if not query_stems:
        return 0.0
    return len(query_stems & content_stems) / len(query_stems)


def _stem(token: str) -> str:
    """Tiny suffix stemmer, only for the no-FTS fallback path."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "i"
    if len(token) > 3 and token.endswith("y"):
        return token[:-1] + "i"
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token
