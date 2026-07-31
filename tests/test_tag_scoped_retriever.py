from types import SimpleNamespace

import pytest

from raganything.query.tag_scoped_retriever import TagScope, retrieve_tag_scoped_context
from raganything.services.kb_tag_repo import TagValidationError, normalize_tag_name


def test_tag_name_normalization_is_stable_and_bounded():
    assert normalize_tag_name("  课程　设计  ") == ("课程 设计", "课程 设计")
    with pytest.raises(TagValidationError):
        normalize_tag_name(" ")
    with pytest.raises(TagValidationError):
        normalize_tag_name("x" * 33)


class _Store:
    def __init__(self):
        self.requested_ids = []
        self.records = {
            "tagged-a": {"chunk_id": "tagged-a", "content": "课程设计包括需求分析和原型验证", "tokens": 12, "file_path": "course-a.pdf", "chunk_order_index": 0},
            "tagged-b": {"chunk_id": "tagged-b", "content": "课程设计需要明确评分标准", "tokens": 11, "file_path": "course-b.pdf", "chunk_order_index": 1},
            "outside": {"chunk_id": "outside", "content": "这段内容绝不能进入标签范围答案", "tokens": 10, "file_path": "outside.pdf", "chunk_order_index": 0},
        }

    async def get_by_ids(self, ids):
        self.requested_ids = list(ids)
        return [self.records[item_id] for item_id in ids if item_id in self.records]


@pytest.mark.asyncio
async def test_tag_scope_reads_and_formats_only_allowed_chunks():
    store = _Store()
    instance = SimpleNamespace(lightrag=SimpleNamespace(text_chunks=store), embedding_func=None)
    scope = TagScope(tag_id=9, tag_name="课程设计", chunk_ids=("tagged-a", "tagged-b"))

    context = await retrieve_tag_scoped_context(instance, scope, "课程设计如何评分", top_k=2)

    assert store.requested_ids == ["tagged-a", "tagged-b"]
    assert "检索范围仅限标签：课程设计" in context
    assert "课程设计包括需求分析" in context
    assert "绝不能进入" not in context
