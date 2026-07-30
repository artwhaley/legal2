import uuid

import pytest

from message_evidence_workstation.client_api.contracts import StreamEvent
from message_evidence_workstation.services.client_workflows import ConversationalWorkflow


def _analysis_plan(*, mode="semantic_ranges", dimensions=3, normalization="unit_l2"):
    plan = {
        "analysis_question": "Identify exchanges responsive to the question.",
        "answer_objective": "Present responsive results and cite their ranges.",
        "concepts": [{
            "label": "responsive exchange",
            "definition": "An exchange that materially answers the question.",
            "manifestations": ["direct discussion", "material indirect discussion"],
        }],
        "inclusion_criteria": ["The passage materially answers the question."],
        "exclusion_criteria": ["The passage is merely adjacent."],
        "answer_requirements": ["State results and cite their ranges."],
        "interpretive_assumptions": [],
    }
    return {
        "request_id": str(uuid.uuid4()),
        "config_version": 13,
        "analysis_plan_id": str(uuid.uuid4()),
        "compatibility_fingerprint": "a" * 64,
        "analysis_plan": plan,
        "retrieval_queries": [
            {"query_id": "q0001", "text": "school fight"},
            {"query_id": "q0002", "text": "argument about school"},
        ],
        "embedding": None if mode == "none" else {
            "embedding_profile_id": "profile-1",
            "artifact_fingerprint": "b" * 64,
            "dimensions": dimensions,
            "normalization": normalization,
        },
        "search_policy": {
            "mode": mode,
            "top_k_per_query": 2,
            "fusion_method": "reciprocal_rank_fusion",
            "rrf_constant": 60,
            "maximum_prompt_suggestion_messages": 40,
        },
        "usage": {
            "input_tokens": 10,
            "output_tokens": 4,
            "source": "provider_reported",
            "estimated_cost": None,
            "cost_complete": False,
            "currency": "USD",
        },
    }


class _Gateway:
    def __init__(self, plan, *, accepted_dimensions=3):
        self.plan = plan
        self.accepted_dimensions = accepted_dimensions
        self.embedding_items = None

    def conversational_plan(self, question):
        assert question == "When did we fight about school?"
        return self.plan

    def embeddings(self, items, **kwargs):
        assert not kwargs
        self.embedding_items = items
        yield StreamEvent({"event": "accepted", "data": {
            "embedding_profile_id": "profile-1",
            "artifact_fingerprint": "b" * 64,
            "dimensions": self.accepted_dimensions,
            "normalization": "unit_l2",
        }})
        yield StreamEvent({"event": "vector_batch", "data": {
            "items": [
                {"message_id": item["message_id"], "vector": [1.0, 0.0, 0.0]}
                for item in items
            ]
        }})
        yield StreamEvent({"event": "completed", "result": {"total_items": len(items)}})


class _Store:
    def __init__(self, candidate_batches):
        self.values = [{"dimensions": 3, "normalization": "unit_l2"}, *candidate_batches]
        self.read_count = 0

    def read(self, fn, *args, **kwargs):
        del fn, args, kwargs
        self.read_count += 1
        return self.values.pop(0)


def _workflow(gateway, store):
    return ConversationalWorkflow(store, None, gateway)


def test_client_embeds_all_plan_queries_once_and_sends_strict_candidates(monkeypatch):
    plan = _analysis_plan()
    gateway = _Gateway(plan)
    store = _Store([
        [
            {"message_id": "m2", "rank": 1, "distance": 0.2},
            {"message_id": "m1", "rank": 2, "distance": 0.4},
        ],
        [
            {"message_id": "m1", "rank": 1, "distance": 0.1},
            {"message_id": "m3", "rank": 2, "distance": 0.5},
        ],
    ])
    monkeypatch.setattr(
        "message_evidence_workstation.services.client_workflows.ClientWorkflowService.message_embedding_candidates_with_vector",
        lambda self, *args, **kwargs: store.values.pop(0),
    )

    context = _workflow(gateway, store)._prepare_analysis_context(
        object(),
        "When did we fight about school?",
        cancellation=None,
        progress=lambda _progress: None,
    )

    assert gateway.embedding_items == [
        {"message_id": "q0001", "text": "school fight"},
        {"message_id": "q0002", "text": "argument about school"},
    ]
    assert context["analysis_plan"] == plan["analysis_plan"]
    assert context["retrieval_queries"] == plan["retrieval_queries"]
    assert context["hits"] == [
        {"query_id": "q0001", "message_id": "m2", "rank": 1, "distance": 0.2},
        {"query_id": "q0001", "message_id": "m1", "rank": 2, "distance": 0.4},
        {"query_id": "q0002", "message_id": "m1", "rank": 1, "distance": 0.1},
        {"query_id": "q0002", "message_id": "m3", "rank": 2, "distance": 0.5},
    ]
    assert all(set(hit) == {"query_id", "message_id", "rank", "distance"} for hit in context["hits"])


def test_none_mode_skips_embedding_and_local_lookup():
    plan = _analysis_plan(mode="none")
    gateway = _Gateway(plan)

    class NoReadStore:
        def read(self, *args, **kwargs):
            raise AssertionError("none mode must not inspect or search the EVW")

    context = _workflow(gateway, NoReadStore())._prepare_analysis_context(
        object(),
        "When did we fight about school?",
        cancellation=None,
        progress=lambda _progress: None,
    )

    assert gateway.embedding_items is None
    assert context["embedding"] is None
    assert context["hits"] == []
    assert context["search_policy"]["mode"] == "none"


def test_client_rejects_embedding_geometry_before_local_search(monkeypatch):
    plan = _analysis_plan()
    gateway = _Gateway(plan, accepted_dimensions=4)
    store = _Store([])
    monkeypatch.setattr(
        "message_evidence_workstation.services.client_workflows.ClientWorkflowService.message_embedding_candidates_with_vector",
        lambda *args, **kwargs: pytest.fail("local search must not run after geometry failure"),
    )

    with pytest.raises(RuntimeError, match="EMBEDDING_CACHE_GEOMETRY_MISMATCH"):
        _workflow(gateway, store)._prepare_analysis_context(
            object(),
            "When did we fight about school?",
            cancellation=None,
            progress=lambda _progress: None,
        )
