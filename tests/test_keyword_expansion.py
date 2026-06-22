"""Keyword expansion parsing and fusion tests."""

from message_evidence_workstation.search.fusion import fuse_hits
from message_evidence_workstation.search.keyword_expansion import parse_expansion_terms
from message_evidence_workstation.search.result_models import SearchHit


def test_parse_json_terms() -> None:
    terms = parse_expansion_terms('{"terms": ["school", "allergy"]}')
    assert terms == ["school", "allergy"]


def test_parse_line_terms() -> None:
    terms = parse_expansion_terms("school\n-allergy")
    assert terms == ["school", "allergy"]


def test_parse_truncated_json_terms() -> None:
    raw = '{"terms": ["benadryl", "diphenhydramine", "allergy medicine", "antihistamine"'
    terms = parse_expansion_terms(raw)
    assert terms == ["benadryl", "diphenhydramine", "allergy medicine", "antihistamine"]


def test_parse_nested_json_string_term() -> None:
    raw = '{"terms": ["{\\"terms\\": [\\"school\\", \\"allergy\\"]}"]}'
    terms = parse_expansion_terms(raw)
    assert "school" in terms
    assert "allergy" in terms


def test_fusion_keeps_single_row_for_direct_and_chip_hit() -> None:
    hits = fuse_hits(
        [
            SearchHit(
                message_id="msg_001",
                source_thread_id="t1",
                match_type="exact",
                retrieval_method="fts_exact",
                query_text="allergy",
            )
        ],
        [
            SearchHit(
                message_id="msg_001",
                source_thread_id="t1",
                match_type="keyword",
                retrieval_method="keyword_expansion",
                query_text="allergy",
                matched_term="school",
            )
        ],
    )
    assert len(hits) == 1
    assert hits[0].match_type == "exact"
