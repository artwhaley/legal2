import json
import uuid

import pytest

from message_evidence_workstation.client_api.gateway import RemoteGateway, RemoteGatewayError
from tests.test_sfv1_retrieval_client import _analysis_plan


def _plan():
    return _analysis_plan(mode="none")


def test_python_gateway_calls_only_the_v4_plan_route(monkeypatch):
    calls = []

    def response(request, timeout):
        calls.append(request.full_url)
        request_id = json.loads(request.data)["request_id"]
        value = _plan()
        value["request_id"] = request_id
        return type("Response", (), {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *args: False,
            "read": lambda self: json.dumps(value).encode("utf-8"),
        })()

    monkeypatch.setattr("urllib.request.urlopen", response)
    result = RemoteGateway("http://server").conversational_plan("question")
    assert calls == ["http://server/v1/conversational-plan"]
    assert result["search_policy"]["mode"] == "none"


def test_python_gateway_rejects_edited_plan_response(monkeypatch):
    def response(request, timeout):
        request_id = json.loads(request.data)["request_id"]
        value = _plan()
        value["request_id"] = request_id
        value["analysis_plan"]["answer_objective"] = " "
        return type("Response", (), {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *args: False,
            "read": lambda self: json.dumps(value).encode("utf-8"),
        })()

    monkeypatch.setattr("urllib.request.urlopen", response)
    with pytest.raises(RemoteGatewayError, match="malformed conversational analysis plan"):
        RemoteGateway("http://server").conversational_plan("question")
