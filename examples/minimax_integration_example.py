"""
MiniMax Integration Example with RAG-Anything

This example demonstrates how to integrate MiniMax with RAG-Anything for
cloud-based text document processing and querying using MiniMax's
OpenAI-compatible API.

MiniMax provides high-quality language models accessible via an API that is
fully compatible with the OpenAI chat completions protocol.

Requirements:
- RAG-Anything installed: pip install raganything
- A MiniMax API key (https://www.minimaxi.com/)
- An embedding service (OpenAI, Ollama, or any OpenAI-compatible endpoint)
  Note: MiniMax does not provide an embedding model, so a separate embedding
  service is required.

Environment Setup:
Create a .env file with:
MINIMAX_API_KEY=your-minimax-api-key

# For embeddings, use any OpenAI-compatible service, e.g.:
EMBEDDING_BINDING_HOST=https://api.openai.com/v1
EMBEDDING_BINDING_API_KEY=your-openai-api-key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536

Quick start:
    export MINIMAX_API_KEY=your-api-key
    python examples/minimax_integration_example.py

API Reference:
- Chat (OpenAI Compatible): https://platform.minimax.io/docs/api-reference/text-openai-api
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

# MiniMax configuration
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_LLM_MODEL = os.getenv("MINIMAX_LLM_MODEL", "MiniMax-M2.7")

# Embedding configuration (MiniMax does not provide an embedding model;
# configure a separate embedding service below)
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BINDING_HOST", "https://api.openai.com/v1")
EMBEDDING_API_KEY = os.getenv(
    "EMBEDDING_BINDING_API_KEY", os.getenv("OPENAI_API_KEY", "")
)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))


def _require_minimax_api_key() -> str:
    """Return the MiniMax API key or fail before LightRAG falls back to OpenAI."""
    if not MINIMAX_API_KEY:
        raise ValueError(
            "MINIMAX_API_KEY is required for MiniMax. "
            "Set it with: export MINIMAX_API_KEY=your-api-key"
        )
    return MINIMAX_API_KEY


def _normalize_minimax_temperature(value):
    """MiniMax accepts temperatures in (0.0, 1.0]; use 1.0 for invalid values."""
    if value is None:
        return 1.0
    try:
        if value <= 0 or value > 1:
            return 1.0
    except TypeError:
        return 1.0
    return value


async def minimax_llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    **kwargs,
) -> str:
    """Top-level LLM function using MiniMax's OpenAI-compatible endpoint.

    MiniMax temperature must be in (0.0, 1.0]; defaults to 1.0.
    """
    # Ensure temperature is within MiniMax's accepted range (0.0, 1.0]
    kwargs["temperature"] = _normalize_minimax_temperature(kwargs.get("temperature"))
    kwargs.setdefault("temperature", 1.0)

    return await openai_complete_if_cache(
        model=MINIMAX_LLM_MODEL,
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=MINIMAX_BASE_URL,
        api_key=_require_minimax_api_key(),
        **kwargs,
    )


async def embedding_func_async(texts: List[str]) -> List[List[float]]:
    """Top-level embedding function (pickle-safe).

    Uses a separate OpenAI-compatible embedding service since MiniMax
    does not provide an embedding model.
    """
    embeddings = await openai_embed(
        texts=texts,
        model=EMBEDDING_MODEL,
        base_url=EMBEDDING_BASE_URL,
        api_key=EMBEDDING_API_KEY,
    )
    return embeddings.tolist()


class MiniMaxRAGIntegration:
    """Integration class for MiniMax with RAG-Anything."""

    def __init__(self):
        self.base_url = MINIMAX_BASE_URL
        self.api_key = MINIMAX_API_KEY
        self.model_name = MINIMAX_LLM_MODEL

        # RAG-Anything configuration
        self.config = RAGAnythingConfig(
            working_dir=f"./rag_storage_minimax/{uuid.uuid4()}",
            parser="mineru",
            parse_method="auto",
            enable_image_processing=False,
            enable_table_processing=True,
            enable_equation_processing=True,
        )
        print(f"📁 Using working_dir: {self.config.working_dir}")

        self.rag = None

    async def test_connection(self) -> bool:
        """Best-effort MiniMax API key and endpoint check."""
        if not self.api_key:
            print("❌ MINIMAX_API_KEY is not set")
            print("   Set it with: export MINIMAX_API_KEY=your-api-key")
            return False

        try:
            from openai import AsyncOpenAI

            print(f"🔌 Testing MiniMax endpoint at: {self.base_url}")
            client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
            try:
                models = await client.models.list()
            except Exception as model_error:
                print(
                    "⚠️  Could not list MiniMax models; continuing because many "
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
                "✅ MiniMax API key is configured; chat completion will verify access."
            )
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            print("💡 Check your MINIMAX_API_KEY and network access to api.minimax.io")
            return False

    async def test_chat_completion(self) -> bool:
        """Test a basic chat completion with MiniMax."""
        try:
            print(f"💬 Testing chat with model: {self.model_name}")
            result = await minimax_llm_model_func(
                "Say 'RAG-Anything MiniMax integration test passed' in one sentence."
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
        """Initialize RAG-Anything with MiniMax as the LLM backend."""
        print("\nInitializing RAG-Anything with MiniMax ...")
        try:
            self.rag = RAGAnything(
                config=self.config,
                llm_model_func=minimax_llm_model_func,
                embedding_func=self._make_embedding_func(),
            )
            print("✅ RAG-Anything initialized successfully!")
            return True
        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            return False

    async def process_document(self, file_path: str):
        """Process a document using MiniMax as the LLM backend."""
        if not self.rag:
            print("❌ Call initialize_rag() first")
            return

        print(f"📄 Processing document: {file_path}")
        await self.rag.process_document_complete(
            file_path=file_path,
            output_dir="./output_minimax",
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
                    "MiniMax Integration with RAG-Anything\n\n"
                    "This integration connects MiniMax's powerful language models "
                    "with RAG-Anything's multimodal document processing pipeline.\n\n"
                    "Key features:\n"
                    "- MiniMax-M2.7: Peak Performance. Ultimate Value. Master the Complex.\n"
                    "- MiniMax-M2.7-highspeed: Same performance, faster and more agile.\n"
                    "- OpenAI-compatible API — no SDK changes required.\n"
                    "- Supports text, table, and equation modalities.\n\n"
                    "Configuration:\n"
                    "  MINIMAX_API_KEY=your-api-key\n"
                    "  MINIMAX_BASE_URL=https://api.minimax.io/v1  (default)\n"
                    "  MINIMAX_LLM_MODEL=MiniMax-M2.7  (default)\n"
                ),
                "page_idx": 0,
            }
        ]

        print("\nInserting sample content ...")
        await self.rag.insert_content_list(
            content_list=content_list,
            file_path="minimax_integration_demo.txt",
            doc_id=f"demo-{uuid.uuid4()}",
            display_stats=True,
        )
        print("✅ Content inserted")

        print("\n🔍 Running sample query ...")
        result = await self.rag.aquery(
            "What MiniMax models are available and what are their characteristics?",
            mode="hybrid",
        )
        print(f"Answer: {result[:400]}")


async def main():
    print("=" * 70)
    print("MiniMax + RAG-Anything Integration Example")
    print("=" * 70)

    integration = MiniMaxRAGIntegration()

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
    print("🚀 Starting MiniMax integration example ...")
    success = asyncio.run(main())
    exit(0 if success else 1)
