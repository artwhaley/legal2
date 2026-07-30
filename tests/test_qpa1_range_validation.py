import pytest

from server.evidence_ledger import LedgerError, WindowLedgerInput, build_ledger, salvage_window_evidence


def _window() -> WindowLedgerInput:
    return WindowLedgerInput(
        "w000001",
        (
            {"message_id": "m1", "thread_id": "t1", "timestamp": "1", "sender": "a", "text": "one"},
            {"message_id": "m2", "thread_id": "t1", "timestamp": "2", "sender": "b", "text": "two"},
            {"message_id": "m3", "thread_id": "t2", "timestamp": "3", "sender": "c", "text": "three"},
            {"message_id": "m4", "thread_id": "t2", "timestamp": "4", "sender": "d", "text": "four"},
            {"message_id": "m5", "thread_id": "t1", "timestamp": "5", "sender": "e", "text": "five"},
        ),
    )


def _range(start: str, end: str, *, thread="t1", summary="summary", relevance="relevance"):
    return {"thread_id": thread, "start_message_id": start, "end_message_id": end, "summary": summary, "relevance": relevance}


def _envelope(ranges, **extra):
    return {"window_id": "w000001", "evidence_ranges": ranges, "uncertainties": [], **extra}


def test_valid_siblings_survive_malformed_first_middle_and_last_entries():
    validated = salvage_window_evidence(_window(), _envelope([
        "not an object",
        _range("m1", "m2"),
        {"thread_id": "t1", "start_message_id": "m1"},
        _range("m5", "m5"),
        {"thread_id": "t1", "start_message_id": "m2", "end_message_id": "missing"},
    ]))
    assert [(item.start_message_id, item.end_message_id) for item in validated.accepted_ranges] == [("m1", "m2"), ("m5", "m5")]
    assert [item.code for item in validated.rejected_ranges] == ["RANGE_NOT_OBJECT", "RANGE_SCHEMA_INVALID", "UNKNOWN_END_MESSAGE_ID"]


def test_unknown_start_and_end_are_rejected_independently():
    validated = salvage_window_evidence(_window(), _envelope([
        _range("missing", "m1"),
        _range("m1", "missing"),
        _range("m1", "m1"),
    ]))
    assert [item.code for item in validated.rejected_ranges] == ["UNKNOWN_START_MESSAGE_ID", "UNKNOWN_END_MESSAGE_ID"]
    assert len(validated.accepted_ranges) == 1


def test_wrong_declared_thread_is_corrected_from_unambiguous_endpoints():
    validated = salvage_window_evidence(_window(), _envelope([_range("m1", "m2", thread="wrong-thread")]))
    assert validated.accepted_ranges[0].thread_id == "t1"
    assert any(item["code"] == "THREAD_ID_CORRECTED" for item in validated.warnings)


def test_valid_endpoint_reversal_is_corrected_and_reported():
    validated = salvage_window_evidence(_window(), _envelope([_range("m2", "m1")]))
    item = validated.accepted_ranges[0]
    assert (item.start_message_id, item.end_message_id) == ("m1", "m2")
    assert item.normalizations == ("endpoint_order_swapped",)
    assert validated.normalizations[0].code == "ENDPOINT_ORDER_SWAPPED"
    assert any(item["code"] == "RANGE_ENDPOINTS_REVERSED" for item in validated.warnings)


def test_cross_thread_and_discontinuous_ranges_are_rejected_without_repair():
    validated = salvage_window_evidence(_window(), _envelope([_range("m1", "m3"), _range("m5", "m1")]))
    assert [item.code for item in validated.rejected_ranges] == ["CROSS_THREAD_RANGE", "NONCONTIGUOUS_THREAD_RANGE"]
    assert validated.normalizations == ()


def test_exact_duplicate_keeps_first_and_overlapping_nonidentical_ranges_survive():
    validated = salvage_window_evidence(_window(), _envelope([
        _range("m1", "m2"), _range("m2", "m1"), _range("m1", "m1"),
    ]))
    assert [(item.start_message_id, item.end_message_id) for item in validated.accepted_ranges] == [("m1", "m2"), ("m1", "m1")]
    assert [item.code for item in validated.rejected_ranges] == ["DUPLICATE_RANGE"]


def test_malformed_uncertainties_and_extra_top_level_fields_warn_without_losing_ranges():
    validated = salvage_window_evidence(
        _window(),
        {"window_id": "w000001", "evidence_ranges": [_range("m1", "m1")], "uncertainties": ["valid", 3], "extra": "ignored"},
    )
    assert len(validated.accepted_ranges) == 1
    assert validated.uncertainties == ("valid",)
    assert len(validated.warnings) == 2


def test_missing_summary_or_relevance_retains_source_identity_without_fabrication():
    validated = salvage_window_evidence(_window(), _envelope([{
        "thread_id": "t1", "start_message_id": "m1", "end_message_id": "m1",
    }]))
    item = validated.accepted_ranges[0]
    assert (item.start_message_id, item.end_message_id, item.thread_id) == ("m1", "m1", "t1")
    assert item.summary is None and item.relevance is None
    assert any(w["details"]["reason"] == "missing_model_description" for w in validated.warnings)


def test_all_invalid_parseable_envelope_is_a_usable_partial_window():
    validated = salvage_window_evidence(_window(), _envelope([_range("missing", "m1"), "bad"]))
    assert validated.accepted_ranges == ()
    assert validated.rejected_range_count == 2
    assert validated.status == "partial"


def test_non_json_or_non_object_envelope_is_machine_unusable():
    with pytest.raises(LedgerError, match="machine-unusable"):
        salvage_window_evidence(_window(), "not-json")
    with pytest.raises(LedgerError, match="machine-unusable"):
        salvage_window_evidence(_window(), {"window_id": "w000001", "evidence_ranges": "not-a-list"})


def test_canonical_ids_follow_window_order_not_completion_order():
    second = WindowLedgerInput("w000002", _window().messages[:2])
    first = _window()
    first_validated = salvage_window_evidence(first, _envelope([_range("m1", "m1")]))
    second_validated = salvage_window_evidence(second, {"window_id": "w000002", "evidence_ranges": [_range("m1", "m2")], "uncertainties": []})
    build = build_ledger([first, second], [first_validated, second_validated])
    assert [record.range_id for record in build.records] == ["r000001", "r000002"]
    assert [record.source_range_index for record in build.records] == [0, 0]
