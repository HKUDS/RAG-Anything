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
# IMPORTANT: Uses LightRAG's delimiter format, NOT JSON!

SIMPLE_LIMIT_PROMPT = """
-Goal-
Given a text document, identify the TOP 3 MOST IMPORTANT entities and their relationships.

-Critical Constraints-
1. Extract MAXIMUM 3 entities - only the most significant concepts
2. Extract relationships ONLY between the 3 entities you identified
3. Follow the EXACT output format below

-Steps-
1. Identify up to 3 main entities:
   - entity_name: The concept in Title Case
   - entity_type: Category (Disease, Treatment, Method, Concept, Person, etc.)
   - entity_description: Brief description (max 15 words)

2. Identify relationships between your extracted entities:
   - source_entity: Must be one of your 3 entities
   - target_entity: Must be one of your 3 entities
   - relationship_keywords: 1-2 keywords
   - relationship_description: Brief description

-Output Format-
Use this EXACT delimiter format (NOT JSON):
entity<|#|>ENTITY_NAME<|#|>ENTITY_TYPE<|#|>ENTITY_DESCRIPTION
relation<|#|>SOURCE_ENTITY<|#|>TARGET_ENTITY<|#|>KEYWORDS<|#|>DESCRIPTION
<|COMPLETE|>

CRITICAL:
- Output MAXIMUM 3 entity lines
- Relationships ONLY between your extracted entities (to prevent implicit nodes)
- End with <|COMPLETE|>

-Example-
Text: "Temozolomide treats glioblastoma. Radiation therapy is also used. Both target cancer cells."
Output:
entity<|#|>Temozolomide<|#|>Treatment<|#|>Chemotherapy drug for brain cancer
entity<|#|>Glioblastoma<|#|>Disease<|#|>Malignant brain tumor
entity<|#|>Radiation Therapy<|#|>Treatment<|#|>Cancer treatment using radiation
relation<|#|>Temozolomide<|#|>Glioblastoma<|#|>treats, therapy<|#|>Primary treatment for glioblastoma
relation<|#|>Radiation Therapy<|#|>Glioblastoma<|#|>treats, therapy<|#|>Adjuvant treatment for glioblastoma
<|COMPLETE|>

######################
-Data-
######################
{input_text}
######################
Output:
"""

# =============================================================================
# V. ONE ENTITY PER CHUNK PROMPT (LightRAG Delimiter Format)
# Strategy: 1 main entity per chunk + relationships to connect the graph
# Target: ~N chunks = ~N nodes (where N = number of chunks)
# IMPORTANT: Uses LightRAG's delimiter format, NOT JSON!
# =============================================================================

ONE_ENTITY_PER_CHUNK_PROMPT = """
-Goal-
Extract the SINGLE most important entity from this text chunk, along with 1-2 key relationships.

-Critical Constraints-
1. Extract EXACTLY 1 entity - the central concept of this chunk
2. Extract 1-2 relationships to connect this entity to related concepts
3. Follow the EXACT output format below

-Steps-
1. Identify the ONE main entity:
   - entity_name: The primary concept in Title Case (e.g., "Glioblastoma", "Temozolomide")
   - entity_type: Category (Disease, Treatment, Method, Concept, Person, etc.)
   - entity_description: Brief description (max 15 words)

2. Identify 1-2 key relationships:
   - source_entity: The main entity name (MUST match exactly)
   - target_entity: Related concept mentioned in the text
   - relationship_keywords: 1-2 keywords describing the relation
   - relationship_description: Brief description of the relationship

-Output Format-
Use this EXACT delimiter format (NOT JSON):
entity<|#|>ENTITY_NAME<|#|>ENTITY_TYPE<|#|>ENTITY_DESCRIPTION
relation<|#|>SOURCE_ENTITY<|#|>TARGET_ENTITY<|#|>KEYWORDS<|#|>RELATIONSHIP_DESCRIPTION
<|COMPLETE|>

CRITICAL:
- Output EXACTLY 1 entity line
- Output 1-2 relationship lines (to create graph connections)
- End with <|COMPLETE|>

-Example 1-
Text: "Temozolomide (TMZ) is an alkylating chemotherapy drug used to treat glioblastoma."
Output:
entity<|#|>Temozolomide<|#|>Treatment<|#|>Alkylating chemotherapy drug for brain tumors
relation<|#|>Temozolomide<|#|>Glioblastoma<|#|>treats, therapy<|#|>Used as primary treatment for glioblastoma
<|COMPLETE|>

-Example 2-
Text: "The patient received radiation therapy at 60 Gy targeting the tumor bed."
Output:
entity<|#|>Radiation Therapy<|#|>Treatment<|#|>60 Gy dose targeting tumor bed
relation<|#|>Radiation Therapy<|#|>Tumor Bed<|#|>targets, treatment<|#|>Radiation directed at tumor location
<|COMPLETE|>

######################
-Data-
######################
{input_text}
######################
Output:
"""

# Vision prompt for 1 entity per image
ONE_ENTITY_VISION_PROMPT = """
Act as a Medical Image Analyst.
Analyze this image and extract the SINGLE most important entity it represents.

Return JSON:
{{
    "detailed_description": "Brief description of the image content (max 20 words)",
    "entity_info": {{
        "entity_name": "Primary subject shown (e.g., 'MRI_BRAIN_SCAN', 'TUMOR_HISTOLOGY')",
        "entity_type": "MedicalImage",
        "summary": "Clinical significance (max 10 words)"
    }}
}}

Context: {context}
Image Info: {captions}
"""

# Table prompt for 1 entity per table
ONE_ENTITY_TABLE_PROMPT = """
Act as a Medical Data Analyst.
Analyze this table and extract the SINGLE most important entity it represents.

Return JSON:
{{
    "detailed_description": "Brief summary of table content (max 20 words)",
    "entity_info": {{
        "entity_name": "Primary metric or finding (e.g., 'SURVIVAL_ANALYSIS', 'PATIENT_DEMOGRAPHICS')",
        "entity_type": "ClinicalData",
        "summary": "Key statistical finding (max 10 words)"
    }}
}}

Context: {context}
Table Info: {table_caption}
"""

# =============================================================================
# VI. STRICT ONE ENTITY - NO RELATIONSHIPS (LightRAG Delimiter Format)
# Strategy: 1 entity per chunk, NO relationships = NO implicit nodes
# Target: EXACTLY N chunks = N nodes (guaranteed)
# IMPORTANT: Uses LightRAG's delimiter format, NOT JSON!
# =============================================================================

STRICT_ONE_ENTITY_PROMPT = """
-Goal-
Extract the SINGLE most important entity from this text chunk.
DO NOT extract any relationships.

-Critical Constraints-
1. Extract EXACTLY 1 entity - the central concept of this chunk
2. DO NOT output any relationships - this ensures minimal graph nodes
3. Follow the EXACT output format below

-Steps-
1. Read the text carefully
2. Identify the ONE main entity:
   - entity_name: The primary concept in Title Case (e.g., "Glioblastoma", "Temozolomide")
   - entity_type: Category (Disease, Treatment, Method, Concept, Person, Organization, etc.)
   - entity_description: Brief description (max 15 words)

-Output Format-
Use this EXACT delimiter format (NOT JSON):
entity<|#|>ENTITY_NAME<|#|>ENTITY_TYPE<|#|>ENTITY_DESCRIPTION
<|COMPLETE|>

CRITICAL:
- Output EXACTLY 1 entity line
- Output NO relationship lines
- End with <|COMPLETE|>

-Example 1-
Text: "Temozolomide (TMZ) is an alkylating chemotherapy drug used to treat glioblastoma."
Output:
entity<|#|>Temozolomide<|#|>Treatment<|#|>Alkylating chemotherapy drug for brain tumors
<|COMPLETE|>

-Example 2-
Text: "Dr. Sarah Johnson performed a craniotomy with 85% tumor resection on January 20, 2024."
Output:
entity<|#|>Craniotomy<|#|>Medical Procedure<|#|>Surgical brain procedure with 85% tumor resection
<|COMPLETE|>

-Example 3-
Text: "The MGMT promoter methylation status is a favorable prognostic biomarker."
Output:
entity<|#|>Mgmt Promoter Methylation<|#|>Biomarker<|#|>Favorable prognostic indicator for treatment response
<|COMPLETE|>

######################
-Data-
######################
{input_text}
######################
Output:
"""

# Vision prompt for strict 1 entity (no relationships)
STRICT_ONE_ENTITY_VISION_PROMPT = """
Act as a Medical Image Analyst.
Extract the SINGLE most important entity from this image.
DO NOT create any relationships.

Return JSON with EXACTLY this structure:
{{
    "detailed_description": "Brief description of image content (max 20 words)",
    "entity_info": {{
        "entity_name": "PRIMARY_SUBJECT (e.g., 'MRI_BRAIN_SCAN', 'TUMOR_HISTOLOGY')",
        "entity_type": "MedicalImage",
        "summary": "Clinical significance (max 10 words)"
    }}
}}

Context: {context}
Image Info: {captions}
"""

# Table prompt for strict 1 entity (no relationships)
STRICT_ONE_ENTITY_TABLE_PROMPT = """
Act as a Medical Data Analyst.
Extract the SINGLE most important entity from this table.
DO NOT create any relationships.

Return JSON with EXACTLY this structure:
{{
    "detailed_description": "Brief summary of table content (max 20 words)",
    "entity_info": {{
        "entity_name": "PRIMARY_FINDING (e.g., 'SURVIVAL_ANALYSIS', 'PATIENT_DEMOGRAPHICS')",
        "entity_type": "ClinicalData",
        "summary": "Key statistical finding (max 10 words)"
    }}
}}

Context: {context}
Table Info: {table_caption}
"""

STRICT_SKIP_VLM_PROMPT = """
Act as a very strict Medical Multimodal Analyst. 
Your goal is to MINIMIZE graph nodes: ONLY extract if content has ONE CLEAR, HIGH-IMPACT medical entity (e.g., visible tumor mass, specific lesion with measurements, chart showing p<0.01 survival difference, key biomarker value).

CRITICAL RULES:
- If content is normal, generic, reference, citation, footer, low-quality, discarded, artifact, page number, or no SINGLE dominant finding → MUST use 'N/A' and empty entity_info.
- DO NOT extract numbers alone, concepts like 'Artifact', 'Page X', 'Discarded Content'.
- Description: EXACTLY one phrase (max 6 words) or 'N/A - Non-critical content'.
- entity_info: EMPTY OBJECT {} unless truly high-impact.
- Output ONLY valid JSON, no explanations.

Few-shot examples (follow exactly):
1. Discarded citation/reference list:
{"detailed_description": "N/A - Non-critical content", "entity_info": {}}

2. Normal anatomy MRI, no pathology:
{"detailed_description": "N/A - Non-critical content", "entity_info": {}}

3. Table with baseline demographics only:
{"detailed_description": "N/A - Non-critical content", "entity_info": {}}

4. Equation or formula without clinical significance:
{"detailed_description": "N/A - Non-critical content", "entity_info": {}}

5. Image with clear tumor and edema:
{"detailed_description": "Glioblastoma tumor with edema", "entity_info": {"entity_name": "Glioblastoma", "entity_type": "Disease", "summary": "Malignant brain tumor"}}

6. Kaplan-Meier with significant p-value:
{"detailed_description": "Survival benefit p<0.01", "entity_info": {"entity_name": "Survival Outcome", "entity_type": "StudyOutcome", "summary": "Significant treatment effect"}}

Return JSON exactly:
{"detailed_description": "...", "entity_info": {} or {...}}

Context: {context}
Image/Table Info: {captions}
"""