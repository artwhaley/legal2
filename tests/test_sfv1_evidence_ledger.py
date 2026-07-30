from server.evidence_ledger import WindowLedgerInput, build_ledger, validate_window_evidence


def _window(window_id="w000001"):
    return WindowLedgerInput(window_id, tuple(
        {"message_id": f"m{i}", "thread_id": "t1", "timestamp": str(i), "sender": "s", "text": f"message {i}"}
        for i in range(1, 4)
    ))


def test_ledger_ids_excerpts_and_coverage_are_deterministic():
    window = _window()
    evidence = validate_window_evidence(window, {"window_id": window.window_id, "evidence_ranges": [{"thread_id": "t1", "start_message_id": "m1", "end_message_id": "m2", "summary": "s", "relevance": "r"}], "uncertainties": []})
    build = build_ledger([window], [evidence])
    assert [record.range_id for record in build.records] == ["r000001"]
    assert [message["message_id"] for message in build.records[0].messages] == ["m1", "m2"]
    assert build.coverage[0].evidence_range_count == 1


def test_invalid_siblings_are_quarantined_without_poisoning_valid_ranges():
    window = _window()
    evidence = validate_window_evidence(window, {"window_id": window.window_id, "evidence_ranges": [{"thread_id": "t1", "start_message_id": "m1", "end_message_id": "m1", "summary": "s", "relevance": "r"}, {"thread_id": "t1", "start_message_id": "missing", "end_message_id": "m2", "summary": "s", "relevance": "r"}], "uncertainties": []})
    build = build_ledger([window], [evidence])
    assert [record.range_id for record in build.records] == ["r000001"]
    assert build.validation["status"] == "partial"
    assert build.validation["rejected_ranges"][0]["code"] == "UNKNOWN_START_MESSAGE_ID"


def test_reversed_opaque_ids_are_normalized_only_by_array_position():
    window = WindowLedgerInput("w000001", (
        {"message_id": "source:20", "thread_id": "t1", "timestamp": "1", "sender": "a", "text": "one"},
        {"message_id": "source:19", "thread_id": "t1", "timestamp": "2", "sender": "b", "text": "two"},
    ))
    evidence = validate_window_evidence(window, {"window_id": window.window_id, "evidence_ranges": [{"thread_id": "t1", "start_message_id": "source:19", "end_message_id": "source:20", "summary": "s", "relevance": "r"}], "uncertainties": []})
    assert evidence.accepted_ranges[0].start_message_id == "source:20"
    assert evidence.accepted_ranges[0].end_message_id == "source:19"
    assert evidence.normalized_range_count == 1
