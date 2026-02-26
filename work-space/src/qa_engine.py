import logging
import json
from pathlib import Path
from raganything import RAGAnything, RAGAnythingConfig
from .models import get_model_funcs
from .config import ENV
from lightrag.utils import EmbeddingFunc

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
            parser=ENV.parser,
            parse_method=ENV.parse_method,
        )

        # Đồng bộ embedding_dim với storage nếu khác ENV (tránh lỗi mismatch khi query kho cũ)
        self.embed_f = self._align_embedding_dim_with_storage(self.storage_dir, self.embed_f)
        
        self.rag = RAGAnything(
            config=config,
            llm_model_func=self.llm_f,
            embedding_func=self.embed_f
        )
        await self.rag._ensure_lightrag_initialized()

    async def query(self, question: str, mode: str = "mix"):
        """
        Thực hiện truy vấn.
        Mode: 'naive', 'local', 'global', 'hybrid', 'mix' (default mix để bật vector search)
        """
        if self.rag is None:
            await self.initialize()
        logger.info(f"Querying: {question} (Mode: {mode})")
        return await self.rag.aquery(question, mode=mode)

    @staticmethod
    def _align_embedding_dim_with_storage(storage_dir: Path, embed_func: EmbeddingFunc) -> EmbeddingFunc:
        """
        Đọc embedding_dim từ VDB lưu trữ; nếu khác với embed_func hiện tại
        thì tạo wrapper cắt/padding để khớp, tránh lỗi mismatch khi load kho cũ.
        """
        vdb_file = storage_dir / "vdb_entities.json"
        if not vdb_file.exists():
            return embed_func

        try:
            with open(vdb_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            stored_dim = data.get("embedding_dim")
            if not stored_dim:
                return embed_func
        except Exception:
            return embed_func

        current_dim = getattr(embed_func, "embedding_dim", None)
        if current_dim == stored_dim or not current_dim:
            return embed_func

        logger.warning(
            f"Embedding dim mismatch detected. Storage: {stored_dim}, current: {current_dim}. "
            "Auto-adjusting query embedding to match storage."
        )

        async def _wrapper(texts):
            maybe = embed_func.func(texts)
            if hasattr(maybe, "__await__"):
                vectors = await maybe
            else:
                vectors = maybe
            adjusted = []
            for vec in vectors:
                if len(vec) > stored_dim:
                    adjusted.append(vec[:stored_dim])
                elif len(vec) < stored_dim:
                    # pad with zeros to expected dim
                    adjusted.append(vec + [0.0] * (stored_dim - len(vec)))
                else:
                    adjusted.append(vec)
            return adjusted

        return EmbeddingFunc(
            embedding_dim=stored_dim,
            max_token_size=embed_func.max_token_size,
            func=_wrapper,
        )
