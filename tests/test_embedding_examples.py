import asyncio
from functools import partial

import numpy as np
from lightrag.utils import EmbeddingFunc


def test_partial_embedding_wrapper_accepts_forwarded_dimensions():
    captured = {}

    async def fake_openai_embed(
        texts,
        model,
        api_key,
        base_url=None,
        embedding_dim=None,
        max_token_size=None,
    ):
        captured["texts"] = texts
        captured["model"] = model
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["embedding_dim"] = embedding_dim
        captured["max_token_size"] = max_token_size
        return np.zeros((len(texts), embedding_dim), dtype=float)

    embedding_func = EmbeddingFunc(
        embedding_dim=4,
        max_token_size=32,
        send_dimensions=True,
        func=partial(
            fake_openai_embed,
            model="text-embedding-v4",
            api_key="test-key",
            base_url="https://example.com/v1",
        ),
    )

    result = asyncio.run(embedding_func(["hello", "world"]))

    assert result.shape == (2, 4)
    assert captured == {
        "texts": ["hello", "world"],
        "model": "text-embedding-v4",
        "api_key": "test-key",
        "base_url": "https://example.com/v1",
        "embedding_dim": 4,
        "max_token_size": 32,
    }
