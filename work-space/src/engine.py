import os
import time
import csv
import logging
from pathlib import Path
from raganything import RAGAnything, RAGAnythingConfig

# Import PROMPTS của RAGAnything
from raganything.prompt import PROMPTS as RAG_PROMPTS 
# Import PROMPTS của LightRAG (MỚI THÊM)
from lightrag.prompt import PROMPTS as LIGHTRAG_PROMPTS

from .config import ENV, ExperimentDef
from .metrics import extract_storage_stats
from .models import get_model_funcs

logger = logging.getLogger("Engine")

class ExperimentEngine:
    def __init__(self):
        self.report_file = Path(ENV.report_file)
        self._ensure_report_header()
        
        # Lưu bản sao lưu của cả 2 thư viện để restore sau này
        self.orig_rag_prompts = RAG_PROMPTS.copy()
        self.orig_lightrag_prompts = LIGHTRAG_PROMPTS.copy()

    def _ensure_report_header(self):
        """Tạo file CSV và header nếu chưa tồn tại"""
        if not self.report_file.exists():
            with open(self.report_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "Experiment_ID", "File_Name", 
                    "Parse_Time(s)", "Graph_Time(s)", "Total_Time(s)", 
                    "Nodes", "Edges", "Chunks", "Entities", "Status"
                ])
    
    def _apply_custom_prompts(self, custom_prompts: dict):
        """Ghi đè prompt của thư viện bằng prompt của thí nghiệm"""
        if not custom_prompts:
            return
        
        logger.info("🔧 Applying custom prompts for this experiment.")
        for key, value in custom_prompts.items():
            
            # CASE 1: Inject vào LightRAG (Dùng key đặc biệt 'lightrag_entity_extract')
            if key == "lightrag_entity_extract":
                LIGHTRAG_PROMPTS["entity_extraction"] = value
                logger.info(f"  - Overridden LightRAG prompt: entity_extraction")
            
            # CASE 2: Inject vào RAGAnything (Vision, Table...)
            elif key in RAG_PROMPTS:
                RAG_PROMPTS[key] = value
                logger.info(f"  - Overridden RAGAnything prompt: {key}")
            
            else:
                logger.warning(f"  - Prompt key '{key}' not found/supported")
    
    def _restore_prompts(self):
        """Khôi phục prompt gốc của cả 2 thư viện"""
        # Restore RAGAnything
        RAG_PROMPTS.clear()
        RAG_PROMPTS.update(self.orig_rag_prompts)
        
        # Restore LightRAG (MỚI THÊM)
        LIGHTRAG_PROMPTS.clear()
        LIGHTRAG_PROMPTS.update(self.orig_lightrag_prompts)
        
        logger.info("🔄 Restored original library prompts.")

    def append_result(self, data: dict):
        """Ghi nối tiếp kết quả vào file CSV"""
        with open(self.report_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"),
                data["exp_id"],
                data["file_name"],
                f"{data['parse_time']:.2f}",
                f"{data['graph_time']:.2f}",
                f"{data['total_time']:.2f}",
                data["nodes"],
                data["edges"],
                data["chunks"],
                data["entities"],
                data["status"]
            ])
        logger.info(f"✅ Saved result for {data['file_name']} to report.")

    async def run_experiment(self, exp_def: ExperimentDef):
        logger.info(f"🚀 STARTING EXPERIMENT: {exp_def.id} (Provider: {exp_def.provider.upper()})")
        logger.info(f"📝 Description: {exp_def.description}")
        
        # 1. Apply Prompt Injection
        self._apply_custom_prompts(exp_def.custom_prompts)

        llm_f, vision_f, embed_f = get_model_funcs(
            provider=exp_def.provider,
            use_gliner=exp_def.use_gliner,
            gliner_labels=exp_def.gliner_labels
        )

        # Định nghĩa thư mục riêng cho Exp này
        exp_dir = Path(ENV.output_base_dir) / exp_def.id
        rag_storage = exp_dir / "rag_storage"
        parser_output = exp_dir / "parser_output"
        
        # Config RAG
        rag_config = RAGAnythingConfig(
            working_dir=str(rag_storage),
            parser_output_dir=str(parser_output),
            parser="mineru",
            parse_method="auto",
            max_concurrent_files=ENV.max_workers,
            **exp_def.raganything_kwargs
        )

        # Init Engine
        rag = RAGAnything(
            config=rag_config,
            llm_model_func=llm_f,
            vision_model_func=vision_f,
            embedding_func=embed_f,
            lightrag_kwargs=exp_def.lightrag_kwargs # Inject params thí nghiệm
        )

        # Scan Input Files
        input_path = Path(ENV.input_dir)
        files = [f for f in input_path.glob("*.*") if f.suffix.lower() in ['.pdf', '.docx']]
        
        if not files:
            logger.warning("No input files found!")
            self._restore_prompts() # Restore trước khi return
            return

        for file_path in files:
            logger.info(f"\n📂 Processing: {file_path.name}")
            t0 = time.time()
            t_parsed = 0
            t_end = 0
            status = "Success"
            
            try:
                # 1. Parse
                content_list, doc_id = await rag.parse_document(
                    str(file_path), 
                    output_dir=str(parser_output), 
                    display_stats=False
                )
                t_parsed = time.time()
                
                # 2. Build Graph
                await rag.insert_content_list(
                    content_list, 
                    str(file_path), 
                    doc_id=doc_id, 
                    display_stats=False
                )
                t_end = time.time()
                
            except Exception as e:
                logger.error(f"❌ Error: {e}")
                status = "Failed"
                t_end = time.time()
                if t_parsed == 0: t_parsed = t_end

            # 3. Collect Metrics
            stats = extract_storage_stats(str(rag_storage))
            
            # 4. Log Result
            result_data = {
                "exp_id": exp_def.id,
                "file_name": file_path.name,
                "parse_time": t_parsed - t0,
                "graph_time": t_end - t_parsed if status == "Success" else 0,
                "total_time": t_end - t0,
                "nodes": stats["nodes"],
                "edges": stats["edges"],
                "chunks": stats["chunks"],
                "entities": stats["entities"],
                "status": status
            }
            
            self.append_result(result_data)
            
        # Cleanup
        if hasattr(rag, 'close'):
            rag.close()
        self._restore_prompts()