import logging
from raganything import RAGAnything, RAGAnythingConfig
from .models import get_model_funcs
from .config import ENV
from pathlib import Path

logger = logging.getLogger("QA_Engine")

class RAGQueryEngine:
    def __init__(self, experiment_id: str):
        self.exp_dir = Path(ENV.output_base_dir) / experiment_id
        self.storage_dir = self.exp_dir / "rag_storage"
        
        # Load Model Funcs (Mặc định dùng Ollama cho query, hoặc lấy từ config exp nếu muốn phức tạp hơn)
        # Ở đây ta hardcode dùng config hiện tại trong .env để query cho tiện
        self.llm_f, _, self.embed_f = get_model_funcs("ollama") # Hoặc 'openai' tùy bạn chọn lúc query
        self.rag = None  

    async def initialize(self):
        """Khởi tạo LightRAG ở chế độ Query (không parse lại)"""
        config = RAGAnythingConfig(
            working_dir=str(self.storage_dir),
            parser="mineru", 
            parse_method="auto"
        )
        
        self.rag = RAGAnything(
            config=config,
            llm_model_func=self.llm_f,
            embedding_func=self.embed_f
        )
        await self.rag._ensure_lightrag_initialized()

    async def query(self, question: str, mode: str = "hybrid"):
        """
        Thực hiện truy vấn.
        Mode: 'naive', 'local', 'global', 'hybrid'
        """
        if self.rag is None:
            await self.initialize()
        logger.info(f"Querying: {question} (Mode: {mode})")
        return await self.rag.aquery(question, mode=mode)