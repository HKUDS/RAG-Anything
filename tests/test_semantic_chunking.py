import numpy as np
import pytest

from raganything import chunking


class _Tokenizer:
    def encode(self, text):
        return text.split()

    def decode(self, tokens):
        return " ".join(tokens)


@pytest.mark.asyncio
async def test_semantic_chunking_batches_embeddings_at_provider_limit_in_order():
    paragraphs = [f"paragraph-{index} body" for index in range(25)]
    calls = []

    async def embedding_func(texts):
        calls.append(list(texts))
        vectors = []
        for text in texts:
            index = int(text.split()[0].split("-")[1])
            vectors.append(
                [1.0, 0.0] if index < 10 else [0.0, 1.0] if index < 20 else [-1.0, 0.0]
            )
        return np.asarray(vectors)

    semantic_chunking = chunking.make_semantic_chunking(embedding_func)
    result = await semantic_chunking(
        _Tokenizer(),
        "\n\n".join(paragraphs),
        chunk_token_size=1000,
    )

    assert [len(batch) for batch in calls] == [10, 10, 5]
    assert [paragraph for batch in calls for paragraph in batch] == paragraphs
    assert [chunk["content"] for chunk in result] == [
        "\n\n".join(paragraphs[:10]),
        "\n\n".join(paragraphs[10:20]),
        "\n\n".join(paragraphs[20:]),
    ]


@pytest.mark.asyncio
async def test_semantic_chunking_honors_a_smaller_configured_batch_size():
    paragraphs = [f"paragraph-{index}" for index in range(11)]
    calls = []

    async def embedding_func(texts):
        calls.append(list(texts))
        return [[1.0, 0.0] for _ in texts]

    semantic_chunking = chunking.make_semantic_chunking(embedding_func, embedding_batch_size=4)
    await semantic_chunking(_Tokenizer(), "\n\n".join(paragraphs), chunk_token_size=1000)

    assert [len(batch) for batch in calls] == [4, 4, 3]


@pytest.mark.asyncio
async def test_semantic_chunking_falls_back_when_a_batch_response_is_incomplete(monkeypatch):
    paragraphs = [f"paragraph-{index}" for index in range(11)]
    fallback = [{"tokens": 1, "content": "recursive fallback", "chunk_order_index": 0}]
    calls = []

    async def embedding_func(texts):
        calls.append(list(texts))
        return [[1.0, 0.0] for _ in texts[:-1]]

    def recursive_fallback(*args, **kwargs):
        return fallback

    monkeypatch.setattr(chunking, "recursive_chunking", recursive_fallback)
    semantic_chunking = chunking.make_semantic_chunking(embedding_func)

    result = await semantic_chunking(_Tokenizer(), "\n\n".join(paragraphs))

    assert result == fallback
    assert [len(batch) for batch in calls] == [10]


@pytest.mark.asyncio
async def test_semantic_chunking_stops_after_a_later_batch_failure(monkeypatch):
    paragraphs = [f"paragraph-{index}" for index in range(25)]
    fallback = [{"tokens": 1, "content": "recursive fallback", "chunk_order_index": 0}]
    calls = []

    async def embedding_func(texts):
        calls.append(list(texts))
        if len(calls) == 2:
            raise RuntimeError("provider unavailable")
        return [[1.0, 0.0] for _ in texts]

    def recursive_fallback(*args, **kwargs):
        return fallback

    monkeypatch.setattr(chunking, "recursive_chunking", recursive_fallback)
    semantic_chunking = chunking.make_semantic_chunking(embedding_func)

    result = await semantic_chunking(_Tokenizer(), "\n\n".join(paragraphs))

    assert result == fallback
    assert [len(batch) for batch in calls] == [10, 10]
