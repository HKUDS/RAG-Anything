from .config import ExperimentDef
from .custom_prompts import SLIM_ENTITY_EXTRACTION_PROMPT

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

EXPERIMENTS = {
    # Exp 1: BASELINE
    # Chạy mặc định của thư viện để lấy số liệu gốc
    "exp1_baseline": ExperimentDef(
        id="exp1_baseline",
        description="Default Settings (Chunk 1200, Auto Gleaning)",
        lightrag_kwargs={}
    ),

    # Exp 2: FAST OPTIMIZATION
    # Gộp ý tưởng: Tăng Chunk Size (2400) + Tắt Gleaning (chỉ quét 1 lần)
    # Mục tiêu: Giảm 50% thời gian, giảm số Node rác
    "exp2_fast_opt": ExperimentDef(
        id="exp2_fast_opt",
        description="Chunk 2400 + Gleaning 1 (Fast Mode)",
        lightrag_kwargs={
            "chunk_token_size": 2400,
            "chunk_overlap_token_size": 200,
            "entity_extract_max_gleaning": 1, 
        }
    ),

    # Exp 3: Text only
    "exp3_text_only": ExperimentDef(
        id="exp3_text_only",
        description="Disable Multimodal Processing (Benchmark Baseline Cost)",
        raganything_kwargs={
            "enable_image_processing": False,
            "enable_table_processing": False,
            "enable_equation_processing": False
        }
    ),
    
    # Exp4: Prompts & Entity Scope cho Full Medical Domain
    "exp4_medical_scope": ExperimentDef(
        id="exp4_medical_scope",
        description="Full Medical Domain (Vision, Table, Text Extraction)",
        
        # 1. Cấu hình cho Text (LightRAG)
        lightrag_kwargs={
            "chunk_token_size": 2400,
            "entity_extract_max_gleaning": 1,
            # Chỉ dẫn LightRAG trích xuất đúng món này
            "addon_params": {
                "entity_types": MEDICAL_ENTITY_TYPES
            }
        },
        
        # 2. Cấu hình cho Multimodal (RAG-Anything)
        custom_prompts={
            "vision_prompt_with_context": MEDICAL_VISION_PROMPT,
            "table_prompt_with_context": MEDICAL_TABLE_PROMPT,
            "generic_prompt_with_context": "Act as a Medical Expert. Analyze this content for clinical relevance..."
        }
    ),

    # # Exp5: OpenAI Provider
    # "exp5_openai_benchmark": ExperimentDef(
    #     id="exp5_openai_benchmark",
    #     description="OpenAI Provider (GPT-4o-mini + GPT-4o)",
    #     provider="openai", 
        
    #     lightrag_kwargs={
    #         "chunk_token_size": 1200,
    #         "entity_extract_max_gleaning": 1,
    #     },
    #     raganything_kwargs={
    #         "enable_image_processing": True
    #     }
    # )

    "exp5_slim_graph": ExperimentDef(
        id="exp5_slim_graph",
        description="Medical Scope + NO Descriptions (Speed Focus)",
        
        lightrag_kwargs={
            "chunk_token_size": 2400,
            "entity_extract_max_gleaning": 1,
            "addon_params": {
                "entity_types": MEDICAL_ENTITY_TYPES
            }
        },
        
        custom_prompts={
            # 1. Ép LightRAG dùng prompt ngắn (cho Text)
            "lightrag_entity_extract": SLIM_ENTITY_EXTRACTION_PROMPT,
            
            # 2. Ép RAGAnything dùng prompt ngắn (cho Ảnh)
            "vision_prompt_with_context": """
            Act as a Medical Researcher. 
            Return JSON with brief findings.
            {
                "detailed_description": "Summary of findings (max 15 words).",
                "entity_info": {
                    "entity_name": "Image Content",
                    "entity_type": "MedicalImage",
                    "summary": "N/A"
                }
            }
            Context: {context}
            Image Info: {captions}
            """
        }
    ),

    "exp6_hybrid_gliner": ExperimentDef(
        id="exp6_hybrid_gliner",
        description="Hybrid: GLiNER (Entities) + Qwen (Relations Only)",
        
        # Bật chế độ Hybrid
        use_gliner=True,
        gliner_labels=MEDICAL_ENTITY_TYPES, # Dùng lại list y tế
        
        lightrag_kwargs={
            "chunk_token_size": 2400,
            "entity_extract_max_gleaning": 1, 
            # Không cần addon_params entity_types nữa vì GLiNER lo rồi
            # Nhưng vẫn để cho chắc nếu fallback
        },
        
        custom_prompts={
            # Vision prompt vẫn giữ ngắn gọn
            "vision_prompt_with_context": "Act as Medical Researcher. Return JSON: {detailed_description: 'Summary (max 20 words)', entity_info: {entity_name: 'Image', summary: 'N/A'}}"
        }
    )
}