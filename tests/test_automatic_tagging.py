from types import SimpleNamespace

import pytest

from raganything.services.auto_tagging import build_automatic_tag_plan
from raganything.services.kb_service import _find_document_status_for_filename


def test_automatic_tagging_defaults_and_runtime_settings(monkeypatch):
    from raganything.services.auto_tagging import automatic_tagging_settings

    monkeypatch.delenv("AUTO_TAG_DOCUMENT_LIMIT", raising=False)
    monkeypatch.delenv("AUTO_TAG_CHUNK_LIMIT", raising=False)
    monkeypatch.delenv("AUTO_TAG_RELATIVE_SCORE_FLOOR", raising=False)
    assert automatic_tagging_settings() == {
        "document_tag_limit": 4,
        "chunk_tag_limit": 8,
        "relative_score_floor": 0.55,
    }

    monkeypatch.setenv("AUTO_TAG_DOCUMENT_LIMIT", "99")
    monkeypatch.setenv("AUTO_TAG_CHUNK_LIMIT", "99")
    monkeypatch.setenv("AUTO_TAG_RELATIVE_SCORE_FLOOR", "2")
    assert automatic_tagging_settings() == {
        "document_tag_limit": 8,
        "chunk_tag_limit": 8,
        "relative_score_floor": 1.0,
    }


def test_automatic_tag_plan_shares_document_keywords_and_keeps_local_keywords_scoped():
    plan = build_automatic_tag_plan(
        [
            {
                "chunk_id": "chunk-1",
                "content": "医疗影像诊断平台使用深度学习识别肺结节和CT扫描结果。",
            },
            {
                "chunk_id": "chunk-2",
                "content": "医疗影像诊断平台需要保护患者隐私并执行数据脱敏流程。",
            },
        ],
        filename="医疗影像诊断方案.docx",
    )

    assert 1 <= len(plan.document_tags) <= 4
    assert set(plan.chunk_tags) == {"chunk-1", "chunk-2"}
    assert all(
        len(plan.document_tags_by_chunk[chunk_id]) + len(tags) <= 8
        for chunk_id, tags in plan.chunk_tags.items()
    )
    assert all(len(tag) <= 32 for tag in plan.document_tags)
    assert all(
        set(tags).isdisjoint(plan.document_tags)
        for tags in plan.chunk_tags.values()
    )


def test_automatic_tag_plan_supports_english_without_model_calls():
    plan = build_automatic_tag_plan(
        [
            {
                "chunk_id": "chunk-a",
                "content": "Kubernetes scheduling coordinates container workloads across production clusters.",
            },
            {
                "chunk_id": "chunk-b",
                "content": "Observability dashboards measure latency and error budgets for Kubernetes services.",
            },
        ],
        filename="kubernetes-operations-guide.md",
    )

    assert plan.document_tags
    assert all(tag.replace("-", "").isalnum() for tag in plan.document_tags)


def test_high_information_technical_chunk_targets_four_to_eight_evidenced_tags():
    content = (
        "发动机冷却系统由散热器、水泵、节温器、冷却液温度传感器和硅油风扇离合器组成。"
        "维护时检查散热器进水软管、出水软管、密封垫和水泵轴承，并按照QSB6维修规范测量冷却液压力。"
    )
    plan = build_automatic_tag_plan([
        {"chunk_id": "cooling", "content": content},
    ])

    tags = (
        plan.document_tags_by_chunk["cooling"]
        + plan.chunk_tags["cooling"]
    )
    assert 4 <= len(tags) <= 8
    assert len({tag.casefold() for tag in tags}) == len(tags)
    assert all(tag.casefold() in content.casefold() for tag in tags)


def test_english_case_and_plural_variants_do_not_create_duplicate_tags():
    content = (
        "Gear diagnostics inspect gears and GEAR tooth wear. "
        "Planetary gearbox sensors record vibration spectra, torque signals, "
        "CAN-Bus messages, and ISO26262 safety events."
    )
    plan = build_automatic_tag_plan([
        {"chunk_id": "gearbox", "content": content},
    ])

    tags = (
        plan.document_tags_by_chunk["gearbox"]
        + plan.chunk_tags["gearbox"]
    )
    normalized = [tag.casefold().removesuffix("s") for tag in tags]
    assert len(normalized) == len(set(normalized))
    assert len(tags) <= 8


def test_chinese_visual_wrapper_fields_are_cleaned_without_losing_domain_terms():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "visual",
            "content": """
                图片内容分析：
                章节路径：发动机 > 冷却系统
                邻近文本：检查散热器进水软管与水泵轴承。
                视觉分析：图中标注节温器壳体、冷却液温度传感器和硅油风扇离合器。
            """,
        },
        {
            "chunk_id": "placeholder",
            "content": """
                图片内容分析：
                章节路径：无
                邻近文本：暂无
                视觉分析：[装饰性占位图]
            """,
        },
    ])

    generated = set(plan.document_tags)
    generated.update(tag for tags in plan.chunk_tags.values() for tag in tags)
    assert not generated.intersection({"图片内容分析", "章节路径", "邻近文本", "视觉分析"})
    assert plan.chunk_tags["placeholder"] == ()
    assert "placeholder" in plan.not_applicable_chunk_ids
    assert plan.chunk_tags["visual"] or plan.document_tags_by_chunk["visual"]


def test_automatic_tag_plan_ignores_persisted_chunk_metadata_terms():
    plan = build_automatic_tag_plan(
        [
            {
                "chunk_id": "chunk-a",
                "content": "idx offset row col header None False MobileNetV3 improves diabetic retinopathy screening.",
            },
        ],
        filename="retinopathy-study.docx",
    )

    generated = set(plan.document_tags)
    generated.update(tag for tags in plan.chunk_tags.values() for tag in tags)
    assert not {"idx", "offset", "row", "col", "header", "None", "False"}.intersection(generated)
    assert "MobileNetV3" in generated or "retinopathy" in generated


def test_automatic_tag_plan_ignores_empty_chunks():
    plan = build_automatic_tag_plan([
        {"chunk_id": "empty", "content": "   "},
        {"content": "missing an id"},
    ])
    assert plan.document_tags == ()
    assert plan.chunk_tags == {"empty": ()}


def test_short_cover_line_is_not_tagged_as_semantic_content():
    plan = build_automatic_tag_plan([
        {"chunk_id": "cover", "content": "郑州经贸学院"},
    ])

    assert plan.eligible_chunk_ids == ()
    assert plan.not_applicable_chunk_ids == ("cover",)
    assert plan.chunk_tags["cover"] == ()
    assert plan.document_tags_by_chunk["cover"] == ()


def test_multimodal_wrapper_labels_and_decorative_fill_never_become_tags():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "engine",
            "content": """
                Image Content Analysis:
                - Section Path: None
                - Neighbor Text: 发动机凸轮轴螺栓需要按规定力矩拧紧。
                Captions: None
                Footnotes: None
                Visual Analysis: The technical schematic depicts an engine camshaft bolt.
            """,
        },
        {
            "chunk_id": "decoration",
            "content": """
                Image Content Analysis:
                - Section Path: None
                - Neighbor Text: None
                Captions: None
                Footnotes: None
                Visual Analysis: [Solid decorative fill]
            """,
        },
    ])

    generated = set(plan.document_tags)
    generated.update(tag for tags in plan.chunk_tags.values() for tag in tags)
    assert not generated.intersection({
        "Analysis", "Neighbor", "Captions", "Footnotes", "Visual",
        "Solid", "decorative", "fill", "technical", "schematic",
    })
    assert plan.chunk_tags["decoration"] == ()
    assert "decoration" in plan.not_applicable_chunk_ids
    assert plan.chunk_tags["engine"] or plan.document_tags_by_chunk["engine"]


def test_media_only_logo_description_is_not_a_keyword_source():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "logo",
            "content": """
                Image Content Analysis:
                - Neighbor Text: None
                Captions: None
                Visual Analysis: The image is a red company logo with a bold emblem on white background.
            """,
        },
        {
            "chunk_id": "repair",
            "content": "发动机凸轮轴与正时皮带需要按维修规范安装。",
        },
    ])

    assert "logo" in plan.not_applicable_chunk_ids
    assert plan.chunk_tags["logo"] == ()
    assert plan.document_tags_by_chunk["logo"] == ()
    generated = set(plan.document_tags)
    generated.update(tag for tags in plan.chunk_tags.values() for tag in tags)
    assert not generated.intersection({"logo", "emblem", "red", "white"})


def test_table_structure_metadata_is_not_a_keyword_source():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "table",
            "content": """
                Table Analysis:
                Caption: None
                Analysis: A 7-row table uses col_span and row_span refs in a fillable
                academic template. The research title is MobileNetV3糖尿病视网膜筛查。
            """,
        },
    ])

    generated = set(plan.document_tags) | set(plan.chunk_tags["table"])
    assert not generated.intersection({"span", "col_span", "row_span", "ref", "fillable"})
    assert generated.intersection({"MobileNetV3", "糖尿病", "视网膜", "筛查"})


def test_processing_error_only_media_chunk_is_not_applicable():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "broken-video",
            "content": """
                Video Content Analysis:
                - Video Path: C:\\uploads\\broken.mp4
                - Duration: 0s
                - Estimated Frames: unknown
                Transcript Preview: [Video processing error: Invalid video file]
                Comprehensive Video Analysis: [Video processing failed: timeout]
            """,
        },
    ])

    assert plan.eligible_chunk_ids == ()
    assert plan.not_applicable_chunk_ids == ("broken-video",)
    assert plan.chunk_tags["broken-video"] == ()


def test_academic_cover_fields_do_not_displace_research_topics():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "cover-and-topic",
            "content": """
                开题报告 学院 专业 班级 学号 学生姓名 指导教师
                基于MobileNetV3的糖尿病视网膜病变快速筛查模型。
            """,
        },
    ], filename="3.开题报告.docx")

    generated = set(plan.document_tags) | set(plan.chunk_tags["cover-and-topic"])
    assert not generated.intersection({"开题", "学院", "专业", "班级", "学号", "学生", "教师"})
    assert generated.intersection({"MobileNetV3", "糖尿病", "视网膜", "筛查", "模型"})


def test_person_names_and_structural_offset_fields_are_rejected():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "metadata",
            "content": """
                Table Analysis:
                Analysis: student name 张三; start_row_offset_idx=4;
                end_row_offset_idx=8; MobileNetV3糖尿病筛查模型。
            """,
        },
    ])

    generated = set(plan.document_tags) | set(plan.chunk_tags["metadata"])
    assert "张三" not in generated
    assert "start_row_offset_idx" not in generated
    assert "end_row_offset_idx" not in generated
    assert generated.intersection({"MobileNetV3", "糖尿病", "筛查", "模型"})


def test_labeled_person_name_is_excluded_from_every_document_chunk():
    plan = build_automatic_tag_plan([
        {"chunk_id": "cover", "content": "学生姓名：程国鸿 指导教师：邱保志"},
        {
            "chunk_id": "body",
            "content": "程国鸿完成MobileNetV3糖尿病视网膜筛查模型，邱保志负责指导。",
        },
    ])

    generated = set(plan.document_tags)
    generated.update(tag for tags in plan.chunk_tags.values() for tag in tags)
    assert "程国鸿" not in generated
    assert "邱保志" not in generated
    assert generated.intersection({"MobileNetV3", "糖尿病", "视网膜", "筛查", "模型"})


def test_table_narrative_person_formats_are_document_metadata():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "table-a",
            "content": "Analysis: Name: 程国鸿; advisor = 邱保志; MobileNetV3筛查。",
        },
        {
            "chunk_id": "table-b",
            "content": "Analysis: '姓名' → '程国鸿'; '姓 名' (Name) = '程国鸿'。",
        },
    ])

    generated = set(plan.document_tags)
    generated.update(tag for tags in plan.chunk_tags.values() for tag in tags)
    assert "程国鸿" not in generated
    assert "邱保志" not in generated


def test_chunk_with_only_rejected_candidates_is_not_applicable():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "generated",
            "content": "Table Analysis:\nAnalysis: ephemeralword appears once in prose.",
        },
        {
            "chunk_id": "domain",
            "content": "MobileNetV3糖尿病视网膜筛查模型。",
        },
    ])

    assert "generated" in plan.not_applicable_chunk_ids
    assert "generated" not in plan.eligible_chunk_ids
    assert plan.chunk_tags["generated"] == ()


def test_short_hashes_and_visual_narration_are_not_keywords():
    plan = build_automatic_tag_plan([
        {
            "chunk_id": "diagram",
            "content": """
                Image Content Analysis:
                Image Path: C:\\output\\8d0b4d54ec53e70e7a7a\\image.png
                Visual Analysis: The primary fallback engineering view uses arrows on a
                possibly textured cylindrical body, while the crankshaft timing chain and
                locking bolt remain visible.
            """,
        },
    ])

    generated = set(plan.document_tags) | set(plan.chunk_tags["diagram"])
    assert not generated.intersection({
        "ec53e70e7a7a", "primary", "fallback", "engineering", "Arrows",
        "possibly", "textured", "cylindrical", "body",
    })
    assert generated.intersection({"crankshaft", "timing", "chain", "locking", "bolt"})


def test_empty_chunk_inherits_document_level_tags():
    plan = build_automatic_tag_plan([
        {"chunk_id": "text", "content": "风险管理流程需要定期复核安全控制措施。"},
        {"chunk_id": "image-only", "content": ""},
    ])

    assert plan.document_tags
    assert plan.chunk_tags["image-only"] == ()


def test_find_document_status_matches_hash_prefixed_upload_name():
    result = _find_document_status_for_filename(
        {
            "doc-1": {"file_path": "uploads/48afe02b_annual-report.docx"},
            "doc-2": {"file_path": "uploads/other.pdf"},
        },
        "annual-report.docx",
    )

    assert result == (
        "doc-1",
        {"file_path": "uploads/48afe02b_annual-report.docx"},
    )


@pytest.mark.asyncio
async def test_uploaded_document_tag_generation_uses_persisted_chunk_ids(monkeypatch):
    from raganything.services import kb_service
    from raganything.services import kb_tag_repo

    async def fake_status(_kb_name, doc_id):
        assert doc_id == "doc-1"
        return {
            "file_path": "c0ffee12_design-guide.md",
            "chunks_count": 2,
            "chunks_list": ["chunk-1", "chunk-2"],
        }

    class Store:
        async def get_by_ids(self, ids):
            assert ids == ["chunk-1", "chunk-2"]
            return [
                {"chunk_id": "chunk-1", "content": "API gateway validates request authorization policies."},
                {"chunk_id": "chunk-2", "content": "API gateway records audit events for security reviews."},
            ]

    async def fake_get_kb(_kb_name):
        return SimpleNamespace(lightrag=SimpleNamespace(text_chunks=Store()))

    recorded = {}
    planning_calls = []

    async def fake_to_thread(function, *args, **kwargs):
        planning_calls.append(function.__name__)
        return function(*args, **kwargs)

    async def fake_replace(
        kb_name, document_id, document_tags, chunk_tags, *, user_id,
        document_tag_names_by_chunk=None,
    ):
        recorded.update({
            "kb_name": kb_name,
            "document_id": document_id,
            "document_tags": tuple(document_tags),
            "chunk_tags": chunk_tags,
            "document_tag_names_by_chunk": document_tag_names_by_chunk,
            "user_id": user_id,
        })
        return {
            "assigned": 4, "skipped": 0, "document_tags": 2, "chunk_tags": 2,
            "tagged_chunk_ids": ["chunk-1", "chunk-2"],
        }

    monkeypatch.setattr(kb_service, "_load_doc_status_by_id", fake_status)
    monkeypatch.setattr(kb_service, "get_kb", fake_get_kb)
    monkeypatch.setattr(kb_service.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(kb_tag_repo, "replace_automatic_document_tags", fake_replace)

    result = await kb_service._generate_uploaded_document_tags(
        "demo", "doc-1", filename="design-guide.md", user_id=17
    )

    assert result["assigned"] == 4
    assert recorded["kb_name"] == "demo"
    assert recorded["document_id"] == "doc-1"
    assert recorded["user_id"] == 17
    assert recorded["document_tags"]
    assert set(recorded["chunk_tags"]) == {"chunk-1", "chunk-2"}
    assert planning_calls == ["build_automatic_tag_plan"]


@pytest.mark.asyncio
async def test_uploaded_document_tag_generation_defers_incomplete_full_status(monkeypatch):
    from raganything.services import kb_service
    from raganything.services import kb_tag_repo

    reads = 0

    async def fake_status(_kb_name, doc_id):
        nonlocal reads
        reads += 1
        assert doc_id == "doc-current"
        return {"chunks_list": [], "chunks_count": 1}

    async def fake_sleep(_seconds):
        return None

    class Store:
        async def get_by_ids(self, ids):
            assert ids == ["chunk-1"]
            return [{"id": "chunk-1", "content": "Access policies require quarterly review."}]

    async def fake_get_kb(_kb_name):
        return SimpleNamespace(lightrag=SimpleNamespace(text_chunks=Store()))

    async def fake_replace(*_args, **_kwargs):
        return {
            "assigned": 1, "skipped": 0, "document_tags": 1, "chunk_tags": 0,
            "tagged_chunk_ids": ["chunk-1"],
        }

    monkeypatch.setattr(kb_service, "_load_doc_status_by_id", fake_status)
    monkeypatch.setattr(kb_service.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(kb_service, "get_kb", fake_get_kb)
    monkeypatch.setattr(kb_tag_repo, "replace_automatic_document_tags", fake_replace)

    with pytest.raises(RuntimeError, match="has no chunk IDs"):
        await kb_service._generate_uploaded_document_tags(
            "demo", "doc-current", filename="current.docx", user_id=17
        )

    assert reads == 1


@pytest.mark.asyncio
async def test_uploaded_document_tag_generation_does_not_repair_missing_chunk_ids(monkeypatch):
    from raganything.services import kb_chunk_repo, kb_service, kb_tag_repo

    async def fake_status(_kb_name, doc_id):
        assert doc_id == "doc-current"
        return {"chunks_count": 2, "chunks_list": []}

    async def fake_sleep(_seconds):
        return None

    class TextStore:
        async def get_by_ids(self, _ids):
            raise AssertionError("empty doc-status must use the PostgreSQL fallback")

    class DocStatusStore:
        def __init__(self):
            self.saved = None
            self.flushed = 0

        async def upsert(self, value):
            self.saved = value

        async def index_done_callback(self):
            self.flushed += 1

    doc_status = DocStatusStore()

    async def fake_get_kb(_kb_name):
        return SimpleNamespace(lightrag=SimpleNamespace(
            text_chunks=TextStore(), doc_status=doc_status,
        ))

    async def fake_query(_lightrag, document_id):
        assert document_id == "doc-current"
        return [
            {"id": "chunk-1", "content": "Security controls are reviewed quarterly."},
            {"id": "chunk-2", "content": "Audit evidence is retained for every review."},
        ]

    recorded = {}

    async def fake_replace(
        _kb, document_id, _document_tags, chunk_tags, *, user_id,
        document_tag_names_by_chunk=None,
    ):
        recorded.update({"document_id": document_id, "chunk_tags": chunk_tags, "user_id": user_id})
        return {
            "assigned": 3, "skipped": 0, "document_tags": 1, "chunk_tags": 2,
            "tagged_chunk_ids": ["chunk-1", "chunk-2"],
        }

    monkeypatch.setattr(kb_service, "_load_doc_status_by_id", fake_status)
    monkeypatch.setattr(kb_service.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(kb_service, "get_kb", fake_get_kb)
    monkeypatch.setattr(kb_chunk_repo, "query_chunks_by_document_id", fake_query)
    monkeypatch.setattr(kb_tag_repo, "replace_automatic_document_tags", fake_replace)

    with pytest.raises(RuntimeError, match="has no chunk IDs"):
        await kb_service._generate_uploaded_document_tags(
            "demo", "doc-current", filename="current.docx", user_id=17
        )

    assert doc_status.saved is None
    assert doc_status.flushed == 0
    assert recorded == {}


@pytest.mark.asyncio
async def test_uploaded_document_tag_generation_defers_partial_chunk_visibility(monkeypatch):
    from raganything.services import kb_chunk_repo, kb_service, kb_tag_repo

    async def fake_status(_kb_name, doc_id):
        assert doc_id == "doc-current"
        return {"chunks_count": 2, "chunks_list": ["chunk-1", "chunk-2"]}

    class TextStore:
        async def get_by_ids(self, _ids):
            return [{"id": "chunk-1", "content": "Only one chunk is visible yet."}]

    class DocStatusStore:
        def __init__(self):
            self.saved = None

        async def upsert(self, value):
            self.saved = value

        async def index_done_callback(self):
            return None

    doc_status = DocStatusStore()

    async def fake_get_kb(_kb_name):
        return SimpleNamespace(lightrag=SimpleNamespace(
            text_chunks=TextStore(), doc_status=doc_status,
        ))

    async def fake_query(_lightrag, _document_id):
        return [
            {"id": "chunk-1", "content": "First durable chunk."},
            {"id": "chunk-2", "content": "Second durable chunk."},
        ]

    written = {}

    async def fake_replace(
        _kb, _document_id, _document_tags, chunk_tags, *, user_id,
        document_tag_names_by_chunk=None,
    ):
        written["chunk_tags"] = chunk_tags
        return {
            "assigned": 2, "skipped": 0, "document_tags": 1, "chunk_tags": 1,
            "tagged_chunk_ids": ["chunk-1", "chunk-2"],
        }

    monkeypatch.setattr(kb_service, "_load_doc_status_by_id", fake_status)
    monkeypatch.setattr(kb_service, "get_kb", fake_get_kb)
    monkeypatch.setattr(kb_chunk_repo, "query_chunks_by_document_id", fake_query)
    monkeypatch.setattr(kb_tag_repo, "replace_automatic_document_tags", fake_replace)

    with pytest.raises(RuntimeError, match="not fully visible"):
        await kb_service._generate_uploaded_document_tags(
            "demo", "doc-current", filename="current.docx", user_id=17
        )

    assert doc_status.saved is None
    assert written == {}


@pytest.mark.asyncio
async def test_verify_document_persisted_uses_unique_staged_upload_filename(monkeypatch):
    from raganything.services import kb_service

    async def fake_statuses(_kb_name):
        return {
            "doc-old": {"file_path": "old12345_opening-report.docx", "status": "processed", "chunks_count": 12},
            "doc-current": {"file_path": "new12345_opening-report.docx", "status": "processed", "chunks_count": 12},
        }

    monkeypatch.setattr(kb_service, "_load_doc_status_json", fake_statuses)

    document_id = await kb_service._verify_document_persisted(
        "demo", "new12345_opening-report.docx"
    )

    assert document_id == "doc-current"


@pytest.mark.asyncio
async def test_uploaded_document_tag_generation_rejects_zero_chunk_status(monkeypatch):
    from raganything.services import kb_chunk_repo, kb_service, kb_tag_repo

    async def fake_status(_kb_name, doc_id):
        assert doc_id == "doc-current"
        return {"chunks_count": 0, "chunks_list": []}

    async def fake_sleep(_seconds):
        return None

    class DocStatusStore:
        async def upsert(self, _value):
            raise AssertionError("no chunks must not repair doc status")

        async def index_done_callback(self):
            raise AssertionError("no chunks must not flush doc status")

    async def fake_get_kb(_kb_name):
        return SimpleNamespace(lightrag=SimpleNamespace(
            text_chunks=SimpleNamespace(), doc_status=DocStatusStore(),
        ))

    async def fake_query(_lightrag, _document_id):
        return []

    async def unexpected_replace(*_args, **_kwargs):
        raise AssertionError("no chunks must not write automatic tags")

    monkeypatch.setattr(kb_service, "_load_doc_status_by_id", fake_status)
    monkeypatch.setattr(kb_service.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(kb_service, "get_kb", fake_get_kb)
    monkeypatch.setattr(kb_chunk_repo, "query_chunks_by_document_id", fake_query)
    monkeypatch.setattr(kb_tag_repo, "replace_automatic_document_tags", unexpected_replace)

    with pytest.raises(RuntimeError, match="has no chunk IDs"):
        await kb_service._generate_uploaded_document_tags(
            "demo", "doc-current", filename="current.docx", user_id=17
        )
