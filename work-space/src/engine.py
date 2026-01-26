import os
import time
import csv
import logging
from pathlib import Path
from raganything import RAGAnything, RAGAnythingConfig

# Import PROMPTS
from raganything.prompt import PROMPTS as RAG_PROMPTS 
from lightrag.prompt import PROMPTS as LIGHTRAG_PROMPTS

from .config import ENV, ExperimentDef
from .metrics import extract_storage_stats
from .models import get_model_funcs

logger = logging.getLogger("Engine")

class ExperimentEngine:
    def __init__(self):
        self.report_file = Path(ENV.report_file)
        self._ensure_report_header()
        self.orig_rag_prompts = RAG_PROMPTS.copy()
        self.orig_lightrag_prompts = LIGHTRAG_PROMPTS.copy()

    def _ensure_report_header(self):
        if not self.report_file.exists():
            with open(self.report_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                # THANG ĐO CHUẨN: Output_Tokens là quan trọng nhất để so sánh công bằng
                writer.writerow([
                    "Timestamp", "Experiment_ID", "File_Name", 
                    "Parse_Time(s)", "Graph_Time(s)", "Total_Time(s)", 
                    "Output_Tokens", "API_Calls", # <-- Đưa lên trước để dễ nhìn
                    "Nodes", "Edges", "Chunks", "Entities", "Relations", 
                    "Status"
                ])
    
    def _apply_custom_prompts(self, custom_prompts: dict):
        if not custom_prompts: return
        logger.info("🔧 Applying custom prompts...")
        for key, value in custom_prompts.items():
            if key == "lightrag_entity_extract":
                LIGHTRAG_PROMPTS["entity_extraction"] = value
            elif key in RAG_PROMPTS:
                RAG_PROMPTS[key] = value

    def _restore_prompts(self):
        RAG_PROMPTS.clear()
        RAG_PROMPTS.update(self.orig_rag_prompts)
        LIGHTRAG_PROMPTS.clear()
        LIGHTRAG_PROMPTS.update(self.orig_lightrag_prompts)

    def append_result(self, data: dict):
        with open(self.report_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"),
                data["exp_id"], data["file_name"],
                f"{data['parse_time']:.2f}", f"{data['graph_time']:.2f}", f"{data['total_time']:.2f}",
                data["Output_Tokens"], data["API_Calls"], # <-- Ghi đúng vị trí
                data["nodes"], data["edges"], data["chunks"], 
                data["entities"], data["relations"], 
                data["status"]
            ])
        logger.info(f"✅ Report updated for {data['file_name']}")

    async def run_experiment(self, exp_def: ExperimentDef):
        logger.info(f"🚀 STARTING: {exp_def.id} (Provider: {exp_def.provider})")
        
        self._apply_custom_prompts(exp_def.custom_prompts)


        current_prompt = LIGHTRAG_PROMPTS.get("entity_extraction", "DEFAULT PROMPT")
        logger.warning(f"🔍 [DEBUG CHECK PROMPT]:\n{current_prompt[:500]}\n...")

        llm_f, vision_f, embed_f = get_model_funcs(exp_def.provider, exp_def.use_gliner, exp_def.gliner_labels)

        exp_dir = Path(ENV.output_base_dir) / exp_def.id
        rag_storage = exp_dir / "rag_storage"
        parser_output = exp_dir / "parser_output"
        
        rag = RAGAnything(
            config=RAGAnythingConfig(
                working_dir=str(rag_storage),
                parser_output_dir=str(parser_output),
                parser="mineru", parse_method="auto",
                max_concurrent_files=ENV.max_workers,
                **exp_def.raganything_kwargs
            ),
            llm_model_func=llm_f, vision_model_func=vision_f, embedding_func=embed_f,
            lightrag_kwargs=exp_def.lightrag_kwargs
        )

        input_path = Path(ENV.input_dir)
        files = [f for f in input_path.glob("*.*") if f.suffix.lower() in ['.pdf', '.docx', '.txt']]
        if not files: return

        for file_path in files:
            logger.info(f"\n📂 Processing: {file_path.name}")
            t0 = time.time()
            t_parsed = 0
            t_end = 0
            status = "Success"
            
            try:
                content_list, doc_id = await rag.parse_document(str(file_path), output_dir=str(parser_output), display_stats=False)
                t_parsed = time.time()
                
                await rag.insert_content_list(content_list, str(file_path), doc_id=doc_id, display_stats=False)
                t_end = time.time()

                # --- FIX QUAN TRỌNG: ÉP GHI DỮ LIỆU RA ĐĨA NGAY LẬP TỨC ---
                # Phải gọi cái này thì file JSON mới có dữ liệu để metrics đọc
                if rag.lightrag:
                    logger.info("💾 Flushing data to disk for metrics calculation...")
                    # Lưu cache LLM (để đếm Token)
                    await rag.lightrag.llm_response_cache.index_done_callback()
                    # Lưu các bảng quan hệ (để đếm Relations/Entities)
                    await rag.lightrag.full_entities.index_done_callback()
                    await rag.lightrag.full_relations.index_done_callback()
                    await rag.lightrag.doc_status.index_done_callback()
                # ----------------------------------------------------------
                
            except Exception as e:
                logger.error(f"❌ Error: {e}")
                status = "Failed"
                t_end = time.time()
                if t_parsed == 0: t_parsed = t_end

            # Đọc số liệu (Lúc này file trên đĩa đã đầy đủ)
            stats = extract_storage_stats(str(rag_storage))
            
            result_data = {
                "exp_id": exp_def.id, "file_name": file_path.name,
                "parse_time": t_parsed - t0, 
                "graph_time": t_end - t_parsed if status == "Success" else 0,
                "total_time": t_end - t0,
                "nodes": stats["nodes"], "edges": stats["edges"], 
                "chunks": stats["chunks"], "entities": stats["entities"], 
                "relations": stats["relations"],
                # Hai chỉ số quan trọng nhất để so sánh công bằng:
                "Output_Tokens": stats["output_tokens"],
                "API_Calls": stats["api_calls"],
                "status": status
            }
            self.append_result(result_data)
            
        if hasattr(rag, 'close'): rag.close()
        self._restore_prompts()