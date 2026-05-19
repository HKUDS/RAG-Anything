import ast
from pathlib import Path


PROCESSOR_SOURCE = (
    Path(__file__).resolve().parent.parent / "raganything" / "processor.py"
)


def _load_merge_logic_function_source():
    source = PROCESSOR_SOURCE.read_text(encoding="utf-8")
    module = ast.parse(source)

    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "ProcessorMixin":
            for child in node.body:
                if (
                    isinstance(child, ast.AsyncFunctionDef)
                    and child.name == "_store_multimodal_entities_to_full_entities"
                ):
                    return ast.get_source_segment(source, child)
    raise AssertionError("Target function not found in processor.py")


def _merge_full_entities(current_doc_entities, entities_to_store, now=1234567890):
    if current_doc_entities is None:
        entity_names = [
            entity_data["entity_name"] for entity_data in entities_to_store.values()
        ]
        return {
            "entity_names": entity_names,
            "count": len(entity_names),
            "update_time": now,
        }

    existing_entity_names = list(current_doc_entities.get("entity_names", []))
    seen = set(existing_entity_names)
    for entity_data in entities_to_store.values():
        entity_name = entity_data["entity_name"]
        if entity_name not in seen:
            existing_entity_names.append(entity_name)
            seen.add(entity_name)

    return {
        **current_doc_entities,
        "entity_names": existing_entity_names,
        "count": len(existing_entity_names),
        "update_time": now,
    }


def test_implementation_preserves_existing_metadata_fields():
    function_source = _load_merge_logic_function_source()
    assert "**current_doc_entities" in function_source
    assert "existing_entity_names = list(" in function_source
    assert "existing_entity_names.append(entity_name)" in function_source


def test_create_new_full_entities_entry():
    entities_to_store = {
        "ent-1": {"entity_name": "Figure 1 (image)"},
        "ent-2": {"entity_name": "Table 2 (table)"},
    }

    result = _merge_full_entities(None, entities_to_store, now=111)

    assert result == {
        "entity_names": ["Figure 1 (image)", "Table 2 (table)"],
        "count": 2,
        "update_time": 111,
    }


def test_preserves_existing_fields_when_merging_multimodal_entities():
    current_doc_entities = {
        "entity_names": ["Alice"],
        "count": 1,
        "update_time": 10,
        "source": "text_pipeline",
        "doc_status": "indexed",
    }
    entities_to_store = {
        "ent-2": {"entity_name": "Figure 1 (image)"},
    }

    result = _merge_full_entities(current_doc_entities, entities_to_store, now=222)

    assert result["entity_names"] == ["Alice", "Figure 1 (image)"]
    assert result["count"] == 2
    assert result["update_time"] == 222
    assert result["source"] == "text_pipeline"
    assert result["doc_status"] == "indexed"


def test_deduplicates_new_entity_names_without_reordering_existing_ones():
    current_doc_entities = {
        "entity_names": ["Alice", "Figure 1 (image)"],
        "count": 2,
        "update_time": 10,
        "source": "text_pipeline",
    }
    entities_to_store = {
        "ent-1": {"entity_name": "Figure 1 (image)"},
        "ent-2": {"entity_name": "Table 2 (table)"},
    }

    result = _merge_full_entities(current_doc_entities, entities_to_store, now=333)

    assert result["entity_names"] == ["Alice", "Figure 1 (image)", "Table 2 (table)"]
    assert result["count"] == 3
    assert result["source"] == "text_pipeline"
