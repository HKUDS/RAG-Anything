from .config import ExperimentDef

EXPERIMENTS = {
    # THÍ NGHIỆM 1: BASELINE
    # Chạy mặc định của thư viện để lấy số liệu gốc
    "exp1_baseline": ExperimentDef(
        id="exp1_baseline",
        description="Default Settings (Chunk 1200, Auto Gleaning)",
        lightrag_kwargs={}
    ),

    # THÍ NGHIỆM 2: FAST OPTIMIZATION
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

    # Thí nghiệm 3: Text only
    "exp3_text_only": ExperimentDef(
        id="exp4_text_only",
        description="Disable Multimodal Processing (Benchmark Baseline Cost)",
        raganything_kwargs={
            "enable_image_processing": False,
            "enable_table_processing": False,
            "enable_equation_processing": False
        }
    )
    
    # Sau này thêm exp4_prompt_tuning tại đây...
}