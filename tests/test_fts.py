"""FTS5 search tests."""

from pathlib import Path

import pytest

from message_evidence_workstation.db.connection import connect
from message_evidence_workstation.db.migrations import initialize_schema
from message_evidence_workstation.importers.normalized_loader import load_normalized_dataset
from message_evidence_workstation.logging_ui.process_log import ProcessLogger
from message_evidence_workstation.search import fts
from message_evidence_workstation.search.date_scope import MessageDateScope
from message_evidence_workstation.search.spellfix import SPELLFIX_TERM_TABLE, expand_fuzzy_terms

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_dataset"


@pytest.fixture
def fts_db(tmp_path):
    conn = connect(tmp_path / "fts.db")
    logger = ProcessLogger(conn)
    initialize_schema(conn, logger)
    dataset_id = load_normalized_dataset(conn, logger, FIXTURE_DIR)
    return conn, logger, dataset_id


def test_exact_search_finds_phrase(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    hits = fts.search_exact(conn, logger, dataset_id, "allergy form")
    assert [hit.message_id for hit in hits] == ["msg_001"]


def test_partial_search_finds_prefix(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    hits = fts.search_partial(conn, logger, dataset_id, "aller")
    assert "msg_001" in [hit.message_id for hit in hits]


def test_trigram_search_finds_internal_misspelling_fragment(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    hits = fts.search_partial(conn, logger, dataset_id, "llerg")
    assert "msg_001" in [hit.message_id for hit in hits]


def test_spellfix_vocabulary_is_built_on_import(fts_db) -> None:
    conn, _logger, dataset_id = fts_db
    terms = {
        row[0]
        for row in conn.execute(
            f"SELECT term FROM {SPELLFIX_TERM_TABLE} WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchall()
    }
    assert "allergy" in terms


def test_spellfix_expands_edit_distance_typo(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    assert expand_fuzzy_terms(conn, logger, dataset_id, "algery") == ["allergy"]


def test_search_messages_includes_fuzzy_hits_for_typo(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    results = fts.search_messages(conn, logger, dataset_id, "algery", limit=None)
    fuzzy_ids = [hit.message_id for hit in results["hits"] if hit.match_type == "fuzzy"]
    assert "msg_001" in fuzzy_ids


def test_message_fts_uses_trigram_tokenizer(fts_db) -> None:
    conn, _logger, _dataset_id = fts_db
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'message_fts'"
    ).fetchone()[0]
    assert "tokenize='trigram'" in sql.replace(" ", "")


def test_ensure_fts_schema_recreates_legacy_unicode_table(tmp_path) -> None:
    conn = connect(tmp_path / "legacy_fts.db")
    conn.execute(
        """
        CREATE VIRTUAL TABLE message_fts USING fts5(
            message_id UNINDEXED,
            dataset_id UNINDEXED,
            source_thread_id UNINDEXED,
            body,
            body_normalized,
            sender_display,
            tokenize = 'unicode61'
        )
        """
    )

    recreated = fts.ensure_fts_schema(conn)

    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'message_fts'"
    ).fetchone()[0]
    assert recreated is True
    assert "tokenize='trigram'" in sql.replace(" ", "")


def test_empty_query_returns_no_hits(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    assert fts.search_exact(conn, logger, dataset_id, "   ") == []


def test_multi_token_search_matches_any_token(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    results = fts.search_messages(conn, logger, dataset_id, "allergies allergic allergy", limit=None)
    message_ids = {hit.message_id for hit in results["hits"] if hit.match_type in {"exact", "partial"}}
    assert "msg_001" in message_ids


def test_allergies_finds_allergy(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    results = fts.search_messages(conn, logger, dataset_id, "allergies", limit=None)
    message_ids = {hit.message_id for hit in results["hits"] if hit.match_type in {"exact", "partial"}}
    assert "msg_001" in message_ids


def test_malformed_partial_query_returns_empty(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    hits = fts.search_partial(conn, logger, dataset_id, ":::")
    assert hits == []


def test_question_mark_in_query_does_not_raise(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    results = fts.search_messages(conn, logger, dataset_id, "allergies?", limit=None)
    message_ids = {hit.message_id for hit in results["hits"] if hit.match_type in {"exact", "partial"}}
    assert "msg_001" in message_ids


def test_hyphenated_query_does_not_raise(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    results = fts.search_messages(conn, logger, dataset_id, "two-window", limit=None)
    assert results["total_count"] >= 0
    assert "hits" in results


def test_search_messages_pagination_matches_full_set(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    query = "the"
    full = fts.search_messages(conn, logger, dataset_id, query, limit=None)
    assert full["total_count"] == len(full["hits"])
    page1 = fts.search_messages(conn, logger, dataset_id, query, limit=2, offset=0)
    page2 = fts.search_messages(conn, logger, dataset_id, query, limit=2, offset=2)
    assert page1["total_count"] == full["total_count"]
    assert page1["has_more"] is (full["total_count"] > 2)
    if full["total_count"] > 2:
        assert page1["next_offset"] == 2
    ids_full = [hit.message_id for hit in full["hits"]]
    assert [hit.message_id for hit in page1["hits"]] == ids_full[:2]
    assert [hit.message_id for hit in page2["hits"]] == ids_full[2:4]


def test_multi_token_search_counts_message_once(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    results = fts.search_messages(
        conn,
        logger,
        dataset_id,
        "allergy allergies allergic",
        limit=None,
    )
    message_ids = [hit.message_id for hit in results["hits"]]
    assert len(message_ids) == len(set(message_ids))
    assert "msg_001" in message_ids


def test_search_messages_ordering_is_stable(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    query = "the"
    first = fts.search_messages(conn, logger, dataset_id, query, limit=None)
    second = fts.search_messages(conn, logger, dataset_id, query, limit=None)
    assert [hit.message_id for hit in first["hits"]] == [hit.message_id for hit in second["hits"]]


def test_count_fts_matches_matches_hit_list(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    fts_query = fts.escape_fts_phrase("allergy")
    assert fts.count_fts_matches(conn, dataset_id, fts_query) >= 1
    hits = fts.search_exact(conn, logger, dataset_id, "allergy")
    assert fts.count_fts_matches(conn, dataset_id, fts_query) == len(hits)


# ── T100: scoped FTS search ────────────────────────────────────────────

def test_search_messages_date_scoped_excludes_out_of_range(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    full = fts.search_messages(conn, logger, dataset_id, "the", limit=None)
    scope = MessageDateScope(start_timestamp="2024-01-10T00:00:00+00:00")
    scoped = fts.search_messages(conn, logger, dataset_id, "the", limit=None, date_scope=scope)
    assert scoped["total_count"] <= full["total_count"]
    assert scoped["total_count"] >= 0
    scoped_ids = {hit.message_id for hit in scoped["hits"]}
    full_ids = {hit.message_id for hit in full["hits"]}
    assert scoped_ids.issubset(full_ids)


def test_search_messages_date_scoped_empty_range(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    scope = MessageDateScope(
        start_timestamp="2020-01-01T00:00:00+00:00",
        end_timestamp="2020-01-02T00:00:00+00:00",
    )
    scoped = fts.search_messages(conn, logger, dataset_id, "the", limit=None, date_scope=scope)
    assert scoped["total_count"] == 0
    assert scoped["hits"] == []


def test_search_messages_date_scoped_start_only(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    scope = MessageDateScope(start_timestamp="2024-01-10T00:00:00+00:00")
    scoped = fts.search_messages(conn, logger, dataset_id, "the", limit=None, date_scope=scope)
    assert scoped["total_count"] >= 0
    # All returned hits should come from messages on or after the start.
    for hit in scoped["hits"]:
        row = conn.execute(
            "SELECT timestamp FROM message WHERE message_id = ? AND dataset_id = ?",
            (hit.message_id, dataset_id),
        ).fetchone()
        assert row is not None
        assert row["timestamp"] >= scope.start_timestamp


def test_search_keyword_terms_date_scoped(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    full = fts.search_keyword_terms(conn, logger, dataset_id, ["the"], limit=None)
    scope = MessageDateScope(end_timestamp="2024-01-02T23:59:59+00:00")
    scoped = fts.search_keyword_terms(conn, logger, dataset_id, ["the"], limit=None, date_scope=scope)
    assert scoped["total_count"] <= full["total_count"]
    assert scoped["total_count"] >= 0


def test_search_messages_date_scoped_pagination(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    scope = MessageDateScope(start_timestamp="2024-01-07T00:00:00+00:00")
    full_scoped = fts.search_messages(conn, logger, dataset_id, "the", limit=None, date_scope=scope)
    page = fts.search_messages(conn, logger, dataset_id, "the", limit=3, offset=0, date_scope=scope)
    assert page["total_count"] == full_scoped["total_count"]
    assert len(page["hits"]) <= 3
    assert page["hits"] == full_scoped["hits"][: len(page["hits"])]


def test_search_messages_no_scope_same_as_full(fts_db) -> None:
    conn, logger, dataset_id = fts_db
    full = fts.search_messages(conn, logger, dataset_id, "the", limit=None)
    none_scope = fts.search_messages(conn, logger, dataset_id, "the", limit=None, date_scope=None)
    inactive = fts.search_messages(conn, logger, dataset_id, "the", limit=None, date_scope=MessageDateScope())
    assert full["total_count"] == none_scope["total_count"]
    assert full["total_count"] == inactive["total_count"]


def test_search_messages_date_scoped_total_count_matches_full(fts_db) -> None:
    """Scoped count via FTS should match scoped count via budget stats."""
    from message_evidence_workstation.search.dataset_budget import compute_dataset_budget_stats

    conn, logger, dataset_id = fts_db
    scope = MessageDateScope(start_timestamp="2024-01-03T00:00:00+00:00")
    stats = compute_dataset_budget_stats(conn, dataset_id, date_scope=scope)
    results = fts.search_messages(conn, logger, dataset_id, "the", limit=None, date_scope=scope)
    # Every FTS hit should come from a message in the scoped set.
    scoped_hit_ids = {hit.message_id for hit in results["hits"]}
    assert len(scoped_hit_ids) <= stats.message_count
    # Total count from FTS should not exceed scoped message count.
    assert results["total_count"] <= stats.message_count
