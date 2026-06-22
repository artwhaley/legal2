"""Embedding adapter tests."""

from message_evidence_workstation.embeddings.adapters import FakeEmbeddingAdapter
from message_evidence_workstation.embeddings.model_registry import EMBEDDING_MODELS, get_model_spec


def test_registry_lists_four_models() -> None:
    assert len(EMBEDDING_MODELS) == 4


def test_fake_adapter_dimensions() -> None:
    adapter = FakeEmbeddingAdapter(dimensions=6)
    info = adapter.load()
    vectors = adapter.embed_texts(["hello", "world"])
    assert info.dimensions == 6
    assert len(vectors) == 2
    assert len(vectors[0]) == 6


def test_get_model_spec() -> None:
    spec = get_model_spec("sentence-transformers/all-MiniLM-L6-v2")
    assert spec is not None
    assert spec.adapter_key == "minilm"
