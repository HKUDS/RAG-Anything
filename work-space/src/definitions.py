from .config import ExperimentDef
from .custom_prompts import SLIM_ENTITY_EXTRACTION_PROMPT, SIMPLE_LIMIT_PROMPT, MEDICAL_VISION_PROMPT, MEDICAL_TABLE_PROMPT, MEDICAL_ENTITY_TYPES

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
            # "vision_prompt_with_context": """
            # Act as a Medical Researcher. 
            # Return JSON with brief findings.
            # {
            #     "detailed_description": "Summary of findings (max 15 words).",
            #     "entity_info": {
            #         "entity_name": "Image Content",
            #         "entity_type": "MedicalImage",
            #         "summary": "N/A"
            #     }
            # }
            # Context: {context}
            # Image Info: {captions}
            # """
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
    ),

    # Exp7: Giới hạn đơn giản chỉ trích xuất Top 3 Entities mỗi Chunk
    "exp7_simple_limit": ExperimentDef(
        id="exp7_simple_limit",
        description="Limit to Top 3 Entities per Chunk (Clean Graph Focus)",
        
        lightrag_kwargs={
            "chunk_token_size": 2400, # Giữ chunk to để có ngữ cảnh rộng
            "entity_extract_max_gleaning": 0,
        },
        
        custom_prompts={
            "lightrag_entity_extract": SIMPLE_LIMIT_PROMPT,
        }
    )

}