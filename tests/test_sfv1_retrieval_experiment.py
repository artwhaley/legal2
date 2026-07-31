import json
from pathlib import Path

import scripts.run_retrieval_hint_experiment as experiment


class FakeCorpus:
    def __init__(self, path: Path, revision_id: int):
        self.path = path
        self.revision_id = revision_id
        self.embedding_dimensions = 3
        self.embedding_normalization = "unit_l2"
        self.messages = [
            {
                "message_id": "m1",
                "thread_id": "t1",
                "timestamp": "2026-01-01T00:00:00Z",
                "sender": "A",
                "text": "SECRET BODY TEXT MUST NOT ENTER ARTIFACTS",
                "ordinal": 0,
                "embedding_input_hash": "a" * 64,
            }
        ]
        self.by_id = {"m1": self.messages[0]}

    def verify_small_revision(self, revision_id: int) -> int:
        return 1

    def resolve_gold(self):
        return [
            {
                "event_date": "2026-01-01",
                "thread_id": "t1",
                "start_message_id": "m1",
                "end_message_id": "m1",
                "start_ordinal": 0,
                "end_ordinal": 0,
            }
        ]

    def vector_rows(self):
        return [{"message_id": "m1", "ordinal": 0, "vector": b"\x00" * 12}]

    def close(self):
        return None


PLAN = {
    "request_id": "00000000-0000-0000-0000-000000000001",
    "config_version": 1,
    "analysis_plan_id": "00000000-0000-0000-0000-000000000002",
    "compatibility_fingerprint": "c" * 64,
    "analysis_plan": {
        "analysis_question": "Show me fights about school.",
        "answer_objective": "Identify responsive conflict evidence.",
        "concepts": [{"label": "school", "definition": "school-related discussion", "manifestations": ["school"]}],
        "inclusion_criteria": ["directly responsive conflict"],
        "exclusion_criteria": ["cooperative logistics without conflict"],
        "retrieval_queries": ["school"],
        "answer_requirements": ["cite direct evidence"],
        "interpretive_assumptions": [],
    },
    "retrieval_queries": [{"query_id": "q0001", "text": "school"}],
    "embedding": {
        "embedding_profile_id": "profile",
        "artifact_fingerprint": "b" * 64,
        "dimensions": 3,
        "normalization": "unit_l2",
    },
    "search_policy": {
        "top_k_per_query": 1,
        "fusion_method": "reciprocal_rank_fusion",
        "rrf_constant": 60,
        "maximum_prompt_suggestion_messages": 1,
    },
    "usage": {
        "input_tokens": 1,
        "output_tokens": 1,
        "source": "estimated",
        "estimated_cost": None,
        "cost_complete": False,
        "currency": "USD",
    },
}


EMBEDDING_EVENTS = [
    {
        "event": "accepted",
        "data": {
            "endpoint": "/v1/embeddings",
            "total_items": 1,
            "embedding_profile_id": "profile",
            "model": "fake",
            "requested_revision": "",
            "artifact_fingerprint": "b" * 64,
            "dimensions": 3,
            "normalization": "unit_l2",
        },
    },
    {"event": "vector_batch", "data": {"items": [{"message_id": "q0001", "vector": [1.0, 0.0, 0.0]}]}},
    {"event": "completed", "result": {"total_items": 1, "embedding_profile_id": "profile"}},
]


ANALYSIS_EVENTS = [
    {"sequence": 1, "event": "window_plan_created", "timestamp": "2026-01-01T00:00:00Z", "data": {"window_plan_hash": "d" * 64, "window_count": 1}},
    {
        "sequence": 2,
        "event": "completed",
        "timestamp": "2026-01-01T00:00:01Z",
        "result": {
            "answer_source": "structured_synthesis",
            "overview": "Answer",
            "raw_answer": None,
            "strategy": "single_window_ledger",
            "evidence_ledger": [{"range_id": "r000001", "window_id": "w0001", "source_range_index": 0, "thread_id": "t1", "start_message_id": "m1", "end_message_id": "m1", "summary": "school conflict", "relevance": "direct", "normalizations": [], "uncertainties": [], "warnings": []}],
            "completion_status": "complete",
            "results": [{"probability": "high_probability", "classification_status": "model_classified", "statement": "Answer", "reported_range_ids": ["r000001"], "verified_range_ids": ["r000001"], "unverified_range_ids": [], "citation_status": "verified", "uncertainty": None, "warnings": []}],
            "unclassified_evidence": [],
            "unverified_model_statements": [],
            "synthesis_validation": {"status": "conformant", "raw_output_preserved": False, "warnings": []},
            "evidence_validation": {"planned_window_count": 1, "usable_window_count": 1, "unavailable_window_count": 0, "unavailable_windows": [], "status": "complete", "accepted_range_count": 1, "rejected_range_count": 0, "normalized_range_count": 0, "rejected_ranges": [], "warnings": []},
            "uncertainties": [],
            "coverage": {"message_count": 1, "planned_window_count": 1, "usable_window_count": 1, "unavailable_window_count": 0, "evidence_range_count": 1},
            "retrieval_diagnostics": {"mode": "semantic_ranges", "query_count": 1, "raw_hit_count": 1, "unique_candidate_message_count": 1, "selected_suggestion_message_count": 1, "suggestion_range_count": 1, "final_ranges_overlapping_suggestions": 1, "final_ranges_outside_suggestions": 0, "answer_relevant_ranges_overlapping_suggestions": 1, "answer_relevant_ranges_outside_suggestions": 0, "suggestions_without_final_evidence": 0},
            "ledger_processing": {"compaction_applied": False, "compaction_levels": 0, "compaction_group_calls": 0},
            "usage": {"input_tokens": 1},
        },
    },
]


class FakeClient:
    instances = []

    def __init__(self, base_url):
        self.base_url = base_url
        self.calls = []
        self.__class__.instances.append(self)

    def json(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path == "/v1/conversational-plan":
            return PLAN
        return {
            "active_config_version": 1,
            "retrieval_assistance_mode": "semantic_ranges",
            "mode_independent_configuration_fingerprint": "e" * 64,
            "configuration_fingerprint": "f" * 64,
            "debug_status": {"active": True, "pending_records": 0, "writer_failure": None, "active_session_id": "20260729T000000Z-aaaaaaaaaaaa"},
        }

    def ndjson(self, path, payload):
        self.calls.append(("POST", path, payload))
        if path == "/v1/embeddings":
            return 200, EMBEDDING_EVENTS
        return 200, ANALYSIS_EVENTS


def test_prepare_freezes_one_plan_and_one_embedding_workload_without_corpus_artifact(
    tmp_path, monkeypatch
):
    fake_corpus = FakeCorpus(tmp_path / "fixture.evw", 4)
    monkeypatch.setattr(experiment, "ReadOnlyCorpus", lambda path, revision_id: fake_corpus)
    monkeypatch.setattr(experiment, "HttpClient", FakeClient)
    monkeypatch.setattr(experiment, "_ensure_debug_capture", lambda client: "20260729T000000Z-aaaaaaaaaaaa")
    monkeypatch.setattr(experiment, "_activate_mode", lambda client, mode: client.json("GET", "/admin/events"))
    monkeypatch.setattr(experiment, "_require_capture", lambda client: client.json("GET", "/admin/events"))
    monkeypatch.setattr(experiment, "_local_candidates", lambda corpus, plan, events: {"q0001": [{"query_id": "q0001", "message_id": "m1", "rank": 1, "distance": 0.0}]})

    output_dir = tmp_path / "run"
    args = type("Args", (), {
        "evw": str(fake_corpus.path),
        "working_corpus_revision_id": 4,
        "server_url": "http://fake",
        "question": experiment.QUESTION,
        "output_dir": str(output_dir),
    })()
    experiment._prepare(args)

    client = FakeClient.instances[-1]
    assert sum(path == "/v1/conversational-plan" for _, path, _ in client.calls) == 1
    assert sum(path == "/v1/embeddings" for _, path, _ in client.calls) == 1
    assert "SECRET BODY TEXT" not in "".join(path.read_text(encoding="utf-8") for path in output_dir.iterdir() if path.is_file())
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["working_corpus_message_count"] == 1
    assert manifest["artifact_hashes"]["raw-candidates.json"]


def test_run_arm_reuses_frozen_plan_and_writes_request_without_corpus_text(tmp_path, monkeypatch):
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    fake_corpus = FakeCorpus(tmp_path / "fixture.evw", 4)
    monkeypatch.setattr(experiment, "ReadOnlyCorpus", lambda path, revision_id: fake_corpus)
    monkeypatch.setattr(experiment, "HttpClient", FakeClient)
    monkeypatch.setattr(experiment, "_activate_mode", lambda client, mode: client.json("GET", "/admin/events"))
    monkeypatch.setattr(experiment, "_require_capture", lambda client: client.json("GET", "/admin/events"))
    experiment._atomic_json(output_dir / "provisional-gold.json", fake_corpus.resolve_gold())
    experiment._atomic_json(output_dir / "analysis-plan.json", PLAN)
    experiment._atomic_json(output_dir / "raw-candidates.json", {"retrieval_queries": {"q0001": [{"query_id": "q0001", "message_id": "m1", "rank": 1, "distance": 0.0}]}})
    experiment._atomic_json(output_dir / "raw-gold-overlap.json", [{"retrieved": True}])
    manifest = {"runner": "QPA1-800", "server_url": "http://fake", "evw": str(fake_corpus.path), "working_corpus_revision_id": 4, "question": experiment.QUESTION, "plan_identity": {"analysis_plan_id": PLAN["analysis_plan_id"], "compatibility_fingerprint": PLAN["compatibility_fingerprint"], "retrieval_queries": PLAN["retrieval_queries"], "embedding": PLAN["embedding"]}, "arms": {}, "capture": {}}
    experiment._write_manifest(output_dir, manifest)
    args = type("Args", (), {"manifest": str(output_dir / "manifest.json"), "arm": "full-semantic", "question": experiment.QUESTION})()
    experiment._run_arm(args)
    request = json.loads((output_dir / "full-semantic-request.json").read_text(encoding="utf-8"))
    assert request["working_corpus_messages_omitted_from_artifact"] is True
    assert "SECRET BODY TEXT" not in (output_dir / "full-semantic-request.json").read_text(encoding="utf-8")
    client = FakeClient.instances[-1]
    assert not any(path == "/v1/conversational-plan" for _, path, _ in client.calls)
    assert not any(path == "/v1/embeddings" for _, path, _ in client.calls)


def test_comparison_markdown_contains_exact_answer_and_complete_ledger(tmp_path):
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    result_artifact = {
        "events": ANALYSIS_EVENTS,
        "metrics": {
            "final_range_inventory": ANALYSIS_EVENTS[-1]["result"]["evidence_ledger"],
        },
    }
    experiment._atomic_json(output_dir / "full-semantic-result.json", result_artifact)
    manifest = {
        "output_dir": str(output_dir),
        "question": experiment.QUESTION,
        "plan_identity": {"retrieval_queries": [{"query_id": "q0001", "text": "school"}]},
        "arms": {
            "full-semantic": {
                "result_artifact": "full-semantic-result.json",
                "metrics": {},
            }
        },
    }
    markdown = experiment._comparison_markdown(
        {
            "valid_apples_to_apples_quality_comparison": True,
            "reasons": [],
            "arms": {
                "full-semantic": {
                    "strategy": "single_window_ledger",
                    "recall": {"count": 1, "total": 1},
                    "outside_suggestion_ranges": 1,
                    "window_plan_hash": "d" * 64,
                }
            },
        },
        manifest,
    )
    assert "### semantic_ranges" in markdown
    assert "Answer" in markdown
    assert "Structured overview" in markdown
    assert '"range_id": "r000001"' in markdown
