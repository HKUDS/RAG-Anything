# Prompt này ép LLM trả về description là "N/A" để tiết kiệm token
SLIM_ENTITY_EXTRACTION_PROMPT = """
-Goal-
Given a text document and a list of entity types, identify all entities and relationships.

-Steps-
1. Identify all entities. For each entity, extract:
- entity_name: Name of the entity, capitalized
- entity_type: One of the following types: [{entity_types}]
- entity_description: MUST be exactly "N/A". Do not generate a description.

2. Identify relationships. For each pair:
- source_entity: name of the source
- target_entity: name of the target
- relationship_description: MUST be exactly "N/A".
- relationship_strength: numeric score
- relationship_keywords: key words

-Output-
Return a single JSON object:
{{
  "entities": [
    {{ "name": "ENTITY_NAME", "type": "ENTITY_TYPE", "description": "N/A" }}
  ],
  "relationships": [
    {{ "source": "E1", "target": "E2", "description": "N/A", "weight": 10, "keywords": "K1, K2" }}
  ]
}}

-Constraints-
1. DO NOT generate descriptions. Use "N/A" to save time.
2. Ensure valid JSON.

-Data-
{input_text}
"""