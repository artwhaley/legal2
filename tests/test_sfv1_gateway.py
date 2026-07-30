import json
import threading

import pytest

from message_evidence_workstation.client_api.gateway import (
    RemoteGateway,
    RemoteGatewayCancelled,
    RemoteGatewayError,
    RequestCancellation,
)


class Headers:
    def get_content_type(self):
        return "application/x-ndjson"


class Response:
    def __init__(self, values):
        self.lines = [(json.dumps(value) + "\n").encode() for value in values]
        self.headers = Headers()
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def __iter__(self): return iter(self.lines)
    def read(self): return b"{}"


def accepted(request_id):
    return {"request_id": request_id, "sequence": 1, "event": "accepted", "timestamp": "2026-01-01T00:00:00Z", "config_version": 7, "data": {"endpoint": "/v1/embeddings", "total_items": 1, "embedding_profile_id": "p", "model": "m", "requested_revision": "r", "artifact_fingerprint": "f", "dimensions": 3, "normalization": "unit_l2"}}


def completed(request_id, sequence=2):
    return {"request_id": request_id, "sequence": sequence, "event": "completed", "timestamp": "2026-01-01T00:00:01Z", "config_version": 7, "result": {"total_items": 1, "embedding_profile_id": "p"}}


def test_gateway_validates_identity_contract_and_terminal_eof(monkeypatch):
    def open_response(request, timeout):
        request_id = json.loads(request.data)["request_id"]
        assert timeout == 9
        return Response([accepted(request_id), completed(request_id)])
    monkeypatch.setattr("urllib.request.urlopen", open_response)
    events = list(RemoteGateway("http://server", timeout_seconds=9).embeddings([{"message_id": "m1", "text": "x"}]))
    assert [event.event for event in events] == ["accepted", "completed"]


@pytest.mark.parametrize("mutate", [
    lambda request_id: [accepted(request_id)],
    lambda request_id: [{**accepted(request_id), "request_id": "different"}, completed(request_id)],
    lambda request_id: [accepted(request_id), {**completed(request_id), "config_version": 8}],
    lambda request_id: [accepted(request_id), completed(request_id), {**completed(request_id, 3)}],
    lambda request_id: [{**accepted(request_id), "data": {"endpoint": "/v1/embeddings"}}, completed(request_id)],
])
def test_gateway_rejects_interrupted_or_inexact_streams(monkeypatch, mutate):
    def open_response(request, timeout):
        request_id = json.loads(request.data)["request_id"]
        return Response(mutate(request_id))
    monkeypatch.setattr("urllib.request.urlopen", open_response)
    with pytest.raises(RemoteGatewayError) as caught:
        list(RemoteGateway("http://server").embeddings([{"message_id": "m1", "text": "x"}]))
    assert caught.value.interrupted


def test_gateway_has_only_v1_product_methods():
    assert not hasattr(RemoteGateway, "capabilities")
    assert not hasattr(RemoteGateway, "window_scan")
    assert not hasattr(RemoteGateway, "evidence_ledger_synthesis")


def test_conversational_stream_can_be_cancelled_by_closing_its_http_response(
    monkeypatch,
):
    entered_read = threading.Event()
    closed = threading.Event()
    caught = []

    class BlockingResponse:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            entered_read.set()
            if not closed.wait(timeout=2):
                raise AssertionError("cancellation did not close the HTTP response")
            raise OSError("response closed")

        def close(self):
            closed.set()

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: BlockingResponse()
    )
    cancellation = RequestCancellation()
    gateway = RemoteGateway("http://server")

    def consume():
        try:
            list(
                gateway.conversational_analysis(
                    question="What happened?",
                    scope_id="scope",
                    messages=[],
                    analysis_context={"analysis_plan_id": "00000000-0000-0000-0000-000000000001"},
                    cancellation=cancellation,
                )
            )
        except Exception as exc:
            caught.append(exc)

    thread = threading.Thread(target=consume)
    thread.start()
    assert entered_read.wait(timeout=2)
    cancellation.cancel()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert len(caught) == 1
    assert isinstance(caught[0], RemoteGatewayCancelled)
