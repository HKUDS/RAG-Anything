from raganything.query_cache import QueryCache, QueryCacheScope
from raganything.query.pipeline import QueryMixin


def test_query_cache_scope_separates_permissions_content_and_settings():
    cache = QueryCache(max_size=10)
    base = QueryCacheScope("kb-a", "user:7", "rev-1", "settings-a", "llm-a")
    other_user = QueryCacheScope("kb-a", "user:8", "rev-1", "settings-a", "llm-a")
    other_revision = QueryCacheScope("kb-a", "user:7", "rev-2", "settings-a", "llm-a")
    other_settings = QueryCacheScope("kb-a", "user:7", "rev-1", "settings-b", "llm-a")

    cache.set("where is the report?", {"answer": "private"}, base)

    assert cache.get("where is the report?", base) == {"answer": "private"}
    assert cache.get("where is the report?", other_user) is None
    assert cache.get("where is the report?", other_revision) is None
    assert cache.get("where is the report?", other_settings) is None


def test_multimodal_cache_key_includes_runtime_scope():
    first = QueryMixin()
    first.query_cache_scope = {
        "workspace": "kb-a",
        "permission_scope": "user:7",
        "corpus_revision": "rev-1",
        "settings_fingerprint": "settings-a",
        "llm_profile_fingerprint": "llm-a",
    }
    other_user = QueryMixin()
    other_user.query_cache_scope = {
        **first.query_cache_scope,
        "permission_scope": "user:8",
    }
    other_revision = QueryMixin()
    other_revision.query_cache_scope = {
        **first.query_cache_scope,
        "corpus_revision": "rev-2",
    }

    key = first._generate_multimodal_cache_key(
        "compare", [{"type": "table", "table_data": "a,b\n1,2"}], "rrf"
    )

    assert key != other_user._generate_multimodal_cache_key(
        "compare", [{"type": "table", "table_data": "a,b\n1,2"}], "rrf"
    )
    assert key != other_revision._generate_multimodal_cache_key(
        "compare", [{"type": "table", "table_data": "a,b\n1,2"}], "rrf"
    )
