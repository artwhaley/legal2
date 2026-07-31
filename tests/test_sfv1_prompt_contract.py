from server.prompts import DEFAULT_PROMPTS


def test_extraction_prompt_defines_opaque_id_and_array_order_contract():
    prompt = DEFAULT_PROMPTS["window_evidence_extraction"]
    assert "Message IDs and thread IDs are opaque strings" in prompt
    assert "frozen analysis plan" in prompt
    assert "Return an empty\nevidence_ranges list" in prompt
    assert "Copy IDs exactly" in prompt


def test_extraction_prompt_makes_retrieval_suggestions_dismissible():
    prompt = DEFAULT_PROMPTS["window_evidence_extraction"]
    assert "identify passages to inspect, not passages to\nreport" in prompt
    assert "is not evidence that a passage answers the plan" in prompt
    assert "dismiss it when its content has no substantive connection" in prompt
    assert "Do not return a range merely because retrieval surfaced it" in prompt
    assert "does not justify\ncollecting clearly unrelated material" in prompt


def test_synthesis_prompt_does_not_launder_retrieval_noise_into_lower_probability():
    prompt = DEFAULT_PROMPTS["ledger_synthesis"]
    assert "Retrieval selection, semantic similarity, shared terms, or a\nprior suggestion is never evidence" in prompt
    assert "Never justify a result by saying that retrieval flagged it" in prompt
    assert "omit it\nfrom results without narrating why it is irrelevant" in prompt
    assert "the caller preserves\nuncited ledger records separately for review" in prompt
    assert "It is not\na catch-all category for unrelated supplied ranges" in prompt
