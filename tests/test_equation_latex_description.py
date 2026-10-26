"""An equation's ``latex`` formula must reach ingestion, not its description.

The documented content-list format is ``{"type": "equation", "latex":
"<formula>", "text": "<description>"}``; ingestion used to prefer ``text``,
so only the description reached the equation prompt and chunk. MinerU items
carry the formula in ``text`` (with ``text_format``) and must not change.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import raganything.modalprocessors as modalprocessors
from raganything.processor import ProcessorMixin
from raganything.prompt import PROMPTS
from raganything.utils import get_equation_description, get_equation_text_and_format

FORMULA = r"P(d|q) = \frac{P(q|d) \cdot P(d)}{P(q)}"
DESCRIPTION = "Document relevance probability formula"
README_ITEM = {"type": "equation", "latex": FORMULA, "text": DESCRIPTION}
MINERU_ITEM = {"type": "equation", "text": FORMULA, "text_format": "latex"}


class RecordingStorage:
    def __init__(self):
        self.records = {}

    async def upsert(self, data):
        self.records.update(data)

    async def get_by_id(self, record_id):
        return self.records.get(record_id)


@pytest.fixture
def processor(monkeypatch):
    lightrag = SimpleNamespace(
        text_chunks=RecordingStorage(),
        chunks_vdb=RecordingStorage(),
        entities_vdb=RecordingStorage(),
        relationships_vdb=RecordingStorage(),
        chunk_entity_relation_graph=SimpleNamespace(upsert_node=AsyncMock()),
        embedding_func=None,
        llm_model_func=None,
        llm_response_cache=None,
        tokenizer=SimpleNamespace(encode=list),
        full_entities=None,
        full_relations=None,
        entity_chunks=None,
        relation_chunks=None,
        _build_global_config=lambda: {},
        _insert_done=AsyncMock(),
    )
    monkeypatch.setattr(modalprocessors, "extract_entities", AsyncMock(return_value=[]))
    monkeypatch.setattr(modalprocessors, "merge_nodes_and_edges", AsyncMock())
    monkeypatch.setattr(
        modalprocessors, "get_namespace_data", AsyncMock(return_value={})
    )
    monkeypatch.setattr(modalprocessors, "get_pipeline_status_lock", lambda: None)

    prompts = []

    async def llm(prompt, system_prompt=None, **kwargs):
        prompts.append(prompt)
        return json.dumps(
            {
                "detailed_description": "Bayes' rule for relevance.",
                "entity_info": {
                    "entity_name": "Relevance Probability",
                    "entity_type": "equation",
                    "summary": "Bayes' rule.",
                },
            }
        )

    instance = modalprocessors.EquationModalProcessor(lightrag, llm)
    instance.prompts = prompts
    return instance


def test_latex_formula_wins_over_description():
    assert get_equation_text_and_format(README_ITEM) == (FORMULA, "latex")
    assert get_equation_description(README_ITEM) == DESCRIPTION


@pytest.mark.parametrize(
    "item",
    [
        MINERU_ITEM,
        {"type": "equation", "text": FORMULA, "text_format": "unknown"},  # Docling
        {"type": "equation", "latex": FORMULA},
        {"type": "equation", "latex": FORMULA, "text": FORMULA},
        {"type": "equation", "equation": FORMULA},
    ],
)
def test_items_without_a_separate_description_are_unchanged(item):
    assert get_equation_text_and_format(item)[0] == FORMULA
    assert get_equation_description(item) == ""


@pytest.mark.asyncio
async def test_readme_item_prompt_and_chunk_carry_the_formula(processor):
    await processor.process_multimodal_content(
        modal_content=README_ITEM,
        content_type="equation",
        file_path="paper.pdf",
        batch_mode=True,
        doc_id="doc-1",
    )

    (prompt,) = processor.prompts
    assert f"Equation: {FORMULA}\nFormat: latex" in prompt
    # The description stays available to the model as context.
    assert f"[Equation: {DESCRIPTION}]" in prompt
    (stored,) = processor.text_chunks_db.records.values()
    assert f"Equation: {FORMULA}\nFormat: latex" in stored["content"]
    assert "Bayes' rule for relevance." in stored["content"]

    chunk = ProcessorMixin()._apply_chunk_template(
        "equation", README_ITEM, "Bayes' rule for relevance."
    )
    assert chunk == stored["content"]


@pytest.mark.asyncio
async def test_mineru_item_prompt_and_chunk_are_unchanged(processor):
    await processor.process_multimodal_content(
        modal_content=MINERU_ITEM,
        content_type="equation",
        file_path="paper.pdf",
        batch_mode=True,
        doc_id="doc-1",
    )

    assert processor.prompts == [
        PROMPTS["equation_prompt"].format(
            equation_text=FORMULA,
            equation_format="latex",
            entity_name="descriptive name for this equation",
        )
    ]
    (stored,) = processor.text_chunks_db.records.values()
    assert stored["content"] == PROMPTS["equation_chunk"].format(
        equation_text=FORMULA,
        equation_format="latex",
        enhanced_caption="Bayes' rule for relevance.",
    )
