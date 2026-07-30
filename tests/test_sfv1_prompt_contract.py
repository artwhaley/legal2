from server.prompts import DEFAULT_PROMPTS


def test_extraction_prompt_defines_opaque_id_and_array_order_contract():
    prompt = DEFAULT_PROMPTS["window_evidence_extraction"]
    assert "Message IDs and thread IDs are opaque strings" in prompt
    assert "frozen analysis plan" in prompt
    assert "Return an empty\nevidence_ranges list" in prompt
    assert "Copy IDs exactly" in prompt
