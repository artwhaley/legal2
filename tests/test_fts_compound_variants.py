"""FTS compound token variant tests."""

from message_evidence_workstation.search.fts import compound_token_variants, token_search_variants


def test_compound_token_variants_cover_spacing_and_hyphen_forms() -> None:
    variants = {variant.casefold() for variant in compound_token_variants("epi-pen")}
    assert "epi-pen" in variants
    assert "epipen" in variants


def test_token_search_variants_include_compound_forms() -> None:
    variants = {variant.casefold() for variant in token_search_variants("epi pen")}
    assert "epi pen" in variants
    assert "epipen" in variants
