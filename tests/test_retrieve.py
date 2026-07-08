from __future__ import annotations

from aetnamem.retrieve import query_tokens, rank_records


def _record(record_id: str, content: str, created_at: str) -> dict:
    return {
        "id": record_id,
        "content": content,
        "created_at": created_at,
        "trust_tier": "trusted_user",
        "status": "active",
    }


def test_query_tokens_drop_stopwords() -> None:
    assert query_tokens("What is my favorite color?") == ["favorite", "color"]


def test_lexical_match_outranks_unrelated_records() -> None:
    records = [
        _record("rec_1", "User's favorite color is teal.", "2026-01-01"),
        _record("rec_2", "User's home city is Sydney.", "2026-01-02"),
    ]
    scored = rank_records("What is my favorite color?", records)
    assert scored[0].record["id"] == "rec_1"
    assert scored[0].text_score > scored[1].text_score


def test_fallback_stemming_matches_plurals() -> None:
    records = [_record("rec_1", "User's itineraries are private.", "2026-01-01")]
    scored = rank_records("Should the itinerary be public?", records)
    assert scored[0].text_score > 0


def test_no_lexical_match_falls_back_to_trust_and_recency() -> None:
    records = [
        _record("rec_1", "User avoids shellfish.", "2026-01-01"),
        _record("rec_2", "User's home city is Sydney.", "2026-01-02"),
    ]
    scored = rank_records("zzz unrelated query", records)
    assert all(item.text_score == 0 for item in scored)
    # Newest record wins on the recency prior.
    assert scored[0].record["id"] == "rec_2"


def test_fts_scores_override_fallback() -> None:
    records = [
        _record("rec_1", "alpha", "2026-01-01"),
        _record("rec_2", "beta", "2026-01-02"),
    ]
    scored = rank_records("beta", records, fts_scores={"rec_1": 5.0})
    assert scored[0].record["id"] == "rec_1"
    assert scored[0].text_score == 1.0
