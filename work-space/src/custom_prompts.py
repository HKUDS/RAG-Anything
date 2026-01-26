# I. Prompt này ép LLM trả về description là "N/A" để tiết kiệm token
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

# II. Prompt này dùng trong chế độ Hybrid, chỉ trích xuất quan hệ giữa các entity đã có sẵn
HYBRID_RELATION_PROMPT = """
-Goal-
You are a Medical Knowledge Graph Expert.
I have already identified the entities in the text using a specialized tool. 
Your job is ONLY to identify the relationships between these provided entities.

-Provided Entities-
{pre_extracted_entities}

-Steps-
1. Review the provided entities.
2. Read the text below.
3. Identify relationships between the provided entities.
4. Output specific description for each entity (briefly, max 5 words) based on the text.

-Output Format-
Return a JSON object:
{{
  "entities": [
    {{ "name": "EXISTING_ENTITY_NAME", "type": "EXISTING_TYPE", "description": "Brief description from text" }}
  ],
  "relationships": [
    {{ "source": "ENTITY_1", "target": "ENTITY_2", "description": "Relation description", "weight": 10, "keywords": "k1, k2" }}
  ]
}}

-Constraints-
1. DO NOT create new entities that are not in the provided list.
2. Only output JSON.

-Data-
{input_text}
"""

# III. PROMPTS CHO RAGANYTHING VỚI NGỮ CẢNH Y TẾ
MEDICAL_VISION_PROMPT = """
Act as a Medical Researcher and Senior Clinician. Analyze this image in a strict medical context.
Identify the image type (e.g., Radiological Scan, Histopathology Slide, Kaplan-Meier Plot, Flowchart, Clinical Photograph).

Provide a JSON response with:
{
    "detailed_description": "Describe findings using standard medical terminology. For scans: mention modality, orientation, anatomical structures, and pathology (lesions, masses). For charts: interpret axes, significant trends, and p-values. For pathology: describe cellular architecture and staining.",
    "entity_info": {
        "entity_name": "Specific condition, anatomical region, or study result shown",
        "entity_type": "MedicalVisualEvidence",
        "summary": "Clinical significance and diagnostic implication of this visual data."
    }
}
Context: {context}
Image Info: {captions}
"""

# B. TABLE PROMPT: Chuyên trị bảng số liệu lâm sàng
# Dùng cho: Patient Demographics, Lab Results, Drug Dosage
MEDICAL_TABLE_PROMPT = """
Act as a Medical Data Analyst. Analyze this clinical data table.
Focus on:
- Patient demographics (n, age, gender distribution)
- Treatment groups and control arms
- Statistical significance (confidence intervals, p-values)
- Clinical outcomes (Adverse events, Efficacy rates)

Provide a JSON response with:
{
    "detailed_description": "Summarize the key clinical findings, statistical comparisons, and significant differences between groups.",
    "entity_info": {
        "entity_name": "Table Content Summary (e.g. Baseline Characteristics)",
        "entity_type": "ClinicalTable",
        "summary": "Key statistical evidence presented in this table."
    }
}
Context: {context}
Table Info: {table_caption}
"""

# C. ENTITY SCOPE (Cho Text Extraction - LightRAG)
# Phủ rộng các khía cạnh y khoa từ cơ sở đến lâm sàng
MEDICAL_ENTITY_TYPES = [
    # Lâm sàng
    "Disease", "Symptom", "Syndrome", "ClinicalSign",
    # Điều trị
    "Medication", "MedicalProcedure", "Therapy", "Dosage",
    # Cận lâm sàng & Cơ sở
    "Anatomy", "Gene", "Protein", "Biomarker", "Pathogen",
    # Nghiên cứu
    "StudyOutcome", "Metric", "PopulationGroup"
]


# IV. Prompt này giới hạn LLM chỉ trích xuất Top 3 entities quan trọng nhất trong mỗi đoạn văn

SIMPLE_LIMIT_PROMPT = """
-Goal-
Given a text document, identify the MOST IMPORTANT entities and relationships.

-Steps-
1. Identify entities. 
   CRITICAL CONSTRAINT: Extract ONLY the Top 3 most significant entities in this text segment. 
   Ignore generic terms or minor details. Focus on the core concepts.
   
   For each entity, extract:
   - entity_name: Name of the entity, capitalized
   - entity_type: General type (e.g. Concept, Person, Event, etc)
   - entity_description: A brief description.

2. Identify relationships.
   Identify pairs of (source_entity, target_entity) from the Top 3 entities identified above.
   
   For each pair:
   - source_entity: name of the source
   - target_entity: name of the target
   - relationship_description: explanation of the relationship
   - relationship_strength: numeric score
   - relationship_keywords: key words

-Output-
Return a single JSON object with the following format:
{{
  "entities": [
    {{ "name": "ENTITY_NAME", "type": "ENTITY_TYPE", "description": "DESCRIPTION" }}
  ],
  "relationships": [
    {{ "source": "E1", "target": "E2", "description": "DESC", "weight": 10, "keywords": "K1, K2" }}
  ]
}}

-Data-
{input_text}
"""

