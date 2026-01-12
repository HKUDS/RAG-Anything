import logging
from gliner import GLiNER

logger = logging.getLogger("GLiNER")

class GlinerService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GlinerService, cls).__new__(cls)
            cls._instance.model = None
        return cls._instance

    def load_model(self, model_name="urchade/gliner_medium-v2.1"):
        """Load model vào GPU/CPU"""
        if self.model is None:
            logger.info(f"📥 Loading GLiNER model: {model_name}...")
            # Tự động dùng CUDA nếu có
            self.model = GLiNER.from_pretrained(model_name)
            logger.info("✅ GLiNER loaded successfully!")
    
    def extract(self, text: str, labels: list):
        """Trích xuất entity trả về format chuỗi JSON-like để nhét vào prompt"""
        if not text or not labels: return "[]"
        
        entities = self.model.predict_entities(text, labels)
        
        # Format lại cho gọn để tiết kiệm token prompt
        # Output: [{"name": "Brain Tumor", "type": "Disease"}, ...]
        simplified_ents = [
            {"name": e["text"], "type": e["label"]} 
            for e in entities
        ]
        return str(simplified_ents)

# Singleton Instance
gliner_service = GlinerService()