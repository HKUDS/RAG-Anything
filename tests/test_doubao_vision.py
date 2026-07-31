import pytest

from raganything.embedding.doubao_vision import DoubaoEmbeddingAdapter


class _FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, _type, _value, _traceback):
        return False

    async def post(self, url, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.response


@pytest.mark.asyncio
async def test_vision_adapter_uses_ark_multimodal_endpoint(monkeypatch):
    import httpx

    calls = []
    response = _FakeResponse(200, {"data": {"embedding": [0.1, 0.2]}})
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(response, calls),
    )
    adapter = DoubaoEmbeddingAdapter(
        api_key="secret", base_url="https://example.test/api/v3/", model="vision-model"
    )

    vectors = await adapter._call_api([{"type": "text", "text": "hello"}])

    assert vectors == [[0.1, 0.2]]
    assert calls == [
        {
            "url": "https://example.test/api/v3/embeddings/multimodal",
            "headers": {
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
            },
            "json": {"model": "vision-model", "input": [{"type": "text", "text": "hello"}]},
        }
    ]


@pytest.mark.asyncio
async def test_vision_adapter_reports_401_and_opens_circuit(monkeypatch):
    import httpx

    calls = []
    response = _FakeResponse(
        401,
        {"code": "Unauthorized", "message": "token is invalid", "request_id": "req-123"},
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(response, calls),
    )
    adapter = DoubaoEmbeddingAdapter(api_key="secret")

    health = await adapter.health_check()
    skipped = await adapter._embed_from_data_uri("data:image/jpeg;base64,AA==")

    assert health["available"] is False
    assert health["disabled_reason"] == "authentication_failed"
    assert health["status_code"] == 401
    assert health["provider_code"] == "Unauthorized"
    assert health["request_id"] == "req-123"
    assert skipped is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_vision_adapter_opens_circuit_for_billing_denial(monkeypatch):
    import httpx

    calls = []
    response = _FakeResponse(
        400,
        {
            "code": "Arrearage",
            "message": "Access denied, please make sure your account is in good standing.",
            "request_id": "req-billing",
        },
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(response, calls),
    )
    adapter = DoubaoEmbeddingAdapter(api_key="secret")

    health = await adapter.health_check()
    skipped = await adapter._embed_from_data_uri("data:image/jpeg;base64,AA==")

    assert health["available"] is False
    assert health["disabled_reason"] == "billing_unavailable"
    assert health["status_code"] == 400
    assert health["provider_code"] == "Arrearage"
    assert skipped is None
    assert len(calls) == 1
