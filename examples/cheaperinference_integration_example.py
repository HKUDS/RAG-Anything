"""
Cheaper Inference Integration Example with RAG-Anything

This example demonstrates how to integrate Cheaper Inference with RAG-Anything
for cloud-based text document processing and querying using Cheaper
Inference's OpenAI-compatible API.

Cheaper Inference is an OpenAI-compatible LLM gateway. One API key gives
access to models from several labs through the OpenAI chat completions
protocol.

Requirements:
- RAG-Anything installed: pip install raganything
- A Cheaper Inference API key (https://cheaperinference.com/signup)
- An embedding service (OpenAI, Ollama, or any OpenAI-compatible endpoint)
  Note: Cheaper Inference does not provide an embedding model, so a separate
  embedding service is required.

Environment Setup:
Create a .env file with:
CHEAPER_INFERENCE_API_KEY=your-cheaper-inference-api-key

# For embeddings, use any OpenAI-compatible service, e.g.:
EMBEDDING_BINDING_HOST=https://api.openai.com/v1
EMBEDDING_BINDING_API_KEY=your-openai-api-key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

Quick start:
    export CHEAPER_INFERENCE_API_KEY=your-api-key
    python examples/cheaperinference_integration_example.py

API Reference:
- Docs: https://cheaperinference.com/docs
- Models: https://cheaperinference.com/markets
"""

import os
import uuid
import asyncio
import inspect
from typing import Dict, List, Optional

from dotenv import load_dotenv

# RAG-Anything imports
from raganything import RAGAnything, RAGAnythingConfig
from lightrag.utils import EmbeddingFunc
from lightrag.llm.openai import openai_complete_if_cache, openai_embed

# Load environment variables
load_dotenv()

# Cheaper Inference configuration
CHEAPER_INFERENCE_BASE_URL = os.getenv(
    "CHEAPER_INFERENCE_BASE_URL", "https://api.cheaperinference.com/v1"
)
CHEAPER_INFERENCE_API_KEY = os.getenv("CHEAPER_INFERENCE_API_KEY", "")
CHEAPER_INFERENCE_LLM_MODEL = os.getenv("CHEAPER_INFERENCE_LLM_MODEL", "gpt-5.4-mini")

# Embedding configuration (Cheaper Inference does not provide an embedding
# model; configure a separate embedding service below)
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BINDING_HOST", "https://api.openai.com/v1")
EMBEDDING_API_KEY = os.getenv(
    "EMBEDDING_BINDING_API_KEY", os.getenv("OPENAI_API_KEY", "")
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))


def _require_cheaper_inference_api_key() -> str:
    """Return the Cheaper Inference API key or fail before LightRAG falls back to OpenAI."""
    if not CHEAPER_INFERENCE_API_KEY:
        raise ValueError(
            "CHEAPER_INFERENCE_API_KEY is required for Cheaper Inference. "
            "Set it with: export CHEAPER_INFERENCE_API_KEY=your-api-key"
        )
    return CHEAPER_INFERENCE_API_KEY


async def cheaperinference_llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    **kwargs,
) -> str:
    """Top-level LLM function using Cheaper Inference's OpenAI-compatible endpoint."""
    return await openai_complete_if_cache(
        model=CHEAPER_INFERENCE_LLM_MODEL,
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=CHEAPER_INFERENCE_BASE_URL,
        api_key=_require_cheaper_inference_api_key(),
        **kwargs,
    )


async def embedding_func_async(texts: List[str]) -> List[List[float]]:
    """Top-level embedding function (pickle-safe).

    Uses a separate OpenAI-compatible embedding service since Cheaper
    Inference does not provide an embedding model.
    """
    embeddings = await openai_embed(
        texts=texts,
        model=EMBEDDING_MODEL,
        base_url=EMBEDDING_BASE_URL,
        api_key=EMBEDDING_API_KEY,
    )
    return embeddings.tolist()


class CheaperInferenceRAGIntegration:
    """Integration class for Cheaper Inference with RAG-Anything."""

    def __init__(self):
        self.base_url = CHEAPER_INFERENCE_BASE_URL
        self.api_key = CHEAPER_INFERENCE_API_KEY
        self.model_name = CHEAPER_INFERENCE_LLM_MODEL

        # RAG-Anything configuration
        self.config = RAGAnythingConfig(
            working_dir=f"./rag_storage_cheaperinference/{uuid.uuid4()}",
            parser="mineru",
            parse_method="auto",
            enable_image_processing=False,
            enable_table_processing=True,
            enable_equation_processing=True,
        )
        print(f"📁 Using working_dir: {self.config.working_dir}")

        self.rag = None

    async def test_connection(self) -> bool:
        """Best-effort Cheaper Inference API key and endpoint check."""
        if not self.api_key:
            print("❌ CHEAPER_INFERENCE_API_KEY is not set")
            print("   Set it with: export CHEAPER_INFERENCE_API_KEY=your-api-key")
            return False

        try:
            from openai import AsyncOpenAI

            print(f"🔌 Testing Cheaper Inference endpoint at: {self.base_url}")
            client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
            try:
                models = await client.models.list()
            except Exception as model_error:
                print(
                    "⚠️  Could not list Cheaper Inference models; continuing because many "
                    f"OpenAI-compatible providers do not expose /v1/models: {model_error}"
                )
            else:
                available = [m.id for m in models.data]
                print(f"✅ Model endpoint returned {len(available)} model(s)")
                for model_id in available[:5]:
                    marker = "🎯" if model_id == self.model_name else "  "
                    print(f"{marker} {model_id}")
                if len(available) > 5:
                    print(f"  ... and {len(available) - 5} more")
            finally:
                close = getattr(client, "close", None) or getattr(
                    client, "aclose", None
                )
                if close:
                    close_result = close()
                    if inspect.isawaitable(close_result):
                        await close_result

            print(
                "✅ Cheaper Inference API key is configured; "
                "chat completion will verify access."
            )
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            print(
                "💡 Check your CHEAPER_INFERENCE_API_KEY and network access to "
                "api.cheaperinference.com"
            )
            return False

    async def test_chat_completion(self) -> bool:
        """Test a basic chat completion with Cheaper Inference."""
        try:
            print(f"💬 Testing chat with model: {self.model_name}")
            result = await cheaperinference_llm_model_func(
                "Say 'RAG-Anything Cheaper Inference integration test passed' "
                "in one sentence."
            )
            print("✅ Chat test successful!")
            print(f"   Response: {result.strip()[:120]}")
            return True
        except Exception as e:
            print(f"❌ Chat test failed: {e}")
            return False

    def _make_embedding_func(self) -> EmbeddingFunc:
        return EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            max_token_size=8192,
            func=embedding_func_async,
        )

    async def initialize_rag(self) -> bool:
        """Initialize RAG-Anything with Cheaper Inference as the LLM backend."""
        print("\nInitializing RAG-Anything with Cheaper Inference ...")
        try:
            self.rag = RAGAnything(
                config=self.config,
                llm_model_func=cheaperinference_llm_model_func,
                embedding_func=self._make_embedding_func(),
            )
            print("✅ RAG-Anything initialized successfully!")
            return True
        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            return False

    async def process_document(self, file_path: str):
        """Process a document using Cheaper Inference as the LLM backend."""
        if not self.rag:
            print("❌ Call initialize_rag() first")
            return

        print(f"📄 Processing document: {file_path}")
        await self.rag.process_document_complete(
            file_path=file_path,
            output_dir="./output_cheaperinference",
            parse_method="auto",
            display_stats=True,
        )
        print("✅ Document processing complete")

    async def simple_query_example(self):
        """Insert sample text and run a demonstration query."""
        if not self.rag:
            print("❌ Call initialize_rag() first")
            return

        content_list = [
            {
                "type": "text",
                "text": (
                    "Cheaper Inference Integration with RAG-Anything\n\n"
                    "This integration connects Cheaper Inference, an "
                    "OpenAI-compatible LLM gateway, with RAG-Anything's "
                    "multimodal document processing pipeline.\n\n"
                    "Key features:\n"
                    "- One API key gives access to models from several labs.\n"
                    "- gpt-5.4-mini: The current default model.\n"
                    "- Set CHEAPER_INFERENCE_LLM_MODEL to use another model.\n"
                    "- OpenAI-compatible API — no SDK changes required.\n"
                    "- Supports text, table, and equation modalities.\n\n"
                    "Configuration:\n"
                    "  CHEAPER_INFERENCE_API_KEY=your-api-key\n"
                    "  CHEAPER_INFERENCE_BASE_URL=https://api.cheaperinference.com/v1  (default)\n"
                    "  CHEAPER_INFERENCE_LLM_MODEL=gpt-5.4-mini  (default)\n"
                ),
                "page_idx": 0,
            }
        ]

        print("\nInserting sample content ...")
        await self.rag.insert_content_list(
            content_list=content_list,
            file_path="cheaperinference_integration_demo.txt",
            doc_id=f"demo-{uuid.uuid4()}",
            display_stats=True,
        )
        print("✅ Content inserted")

        print("\n🔍 Running sample query ...")
        result = await self.rag.aquery(
            "How do I configure Cheaper Inference and which model is the default?",
            mode="hybrid",
        )
        print(f"Answer: {result[:400]}")


async def main():
    print("=" * 70)
    print("Cheaper Inference + RAG-Anything Integration Example")
    print("=" * 70)

    integration = CheaperInferenceRAGIntegration()

    if not await integration.test_connection():
        return False

    print()
    if not await integration.test_chat_completion():
        return False

    print("\n" + "─" * 50)
    if not await integration.initialize_rag():
        return False

    # Uncomment to process a real document:
    # await integration.process_document("path/to/your/document.pdf")

    await integration.simple_query_example()

    print("\n" + "=" * 70)
    print("Integration example completed successfully!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    print("🚀 Starting Cheaper Inference integration example ...")
    success = asyncio.run(main())
    exit(0 if success else 1)
