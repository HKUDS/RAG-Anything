"""
OrcaRouter Integration Example with RAG-Anything

This example demonstrates how to integrate OrcaRouter with RAG-Anything for
cloud-based multimodal document processing and querying using OrcaRouter's
OpenAI-compatible API.

OrcaRouter (https://www.orcarouter.ai) is an OpenAI-compatible model-routing
gateway. A single API key routes to 150+ models from OpenAI, Anthropic, Google,
DeepSeek, Qwen, MiniMax, xAI and more, and it exposes both chat completions and
embeddings behind one endpoint — so one OrcaRouter key covers the LLM and the
embedding service in this example.

Requirements:
- RAG-Anything installed: pip install raganything
- An OrcaRouter API key (https://www.orcarouter.ai — keys start with sk-orca-)

Environment Setup:
Create a .env file with:
ORCAROUTER_API_KEY=sk-orca-your-api-key

# Optional overrides (defaults shown):
# ORCAROUTER_BASE_URL=https://api.orcarouter.ai/v1
# ORCAROUTER_LLM_MODEL=orcarouter/auto
# ORCAROUTER_EMBEDDING_MODEL=openai/text-embedding-3-small
# ORCAROUTER_EMBEDDING_DIM=1536

Quick start:
    export ORCAROUTER_API_KEY=sk-orca-your-api-key
    python examples/orcarouter_integration_example.py

API Reference:
- Models catalog: https://www.orcarouter.ai/models
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

# OrcaRouter configuration
ORCAROUTER_BASE_URL = os.getenv("ORCAROUTER_BASE_URL", "https://api.orcarouter.ai/v1")
ORCAROUTER_API_KEY = os.getenv("ORCAROUTER_API_KEY", "")
ORCAROUTER_LLM_MODEL = os.getenv("ORCAROUTER_LLM_MODEL", "orcarouter/auto")

# Embedding configuration — OrcaRouter serves embeddings on the same endpoint
# and key as the LLM, so a separate embedding service is not required.
ORCAROUTER_EMBEDDING_MODEL = os.getenv(
    "ORCAROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small"
)
ORCAROUTER_EMBEDDING_DIM = int(os.getenv("ORCAROUTER_EMBEDDING_DIM", "1536"))


def _require_orcarouter_api_key() -> str:
    """Return the OrcaRouter API key or fail before LightRAG falls back to OpenAI."""
    if not ORCAROUTER_API_KEY:
        raise ValueError(
            "ORCAROUTER_API_KEY is required for OrcaRouter. "
            "Set it with: export ORCAROUTER_API_KEY=your-api-key"
        )
    return ORCAROUTER_API_KEY


async def orcarouter_llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    **kwargs,
) -> str:
    """Top-level LLM function using OrcaRouter's OpenAI-compatible endpoint.

    Model ids are router ids (e.g. ``orcarouter/auto``, ``openai/gpt-4o``,
    ``anthropic/claude-sonnet-4.6``) that the gateway resolves to an upstream
    model.
    """
    return await openai_complete_if_cache(
        model=ORCAROUTER_LLM_MODEL,
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=ORCAROUTER_BASE_URL,
        api_key=_require_orcarouter_api_key(),
        **kwargs,
    )


async def embedding_func_async(texts: List[str]) -> List[List[float]]:
    """Top-level embedding function (pickle-safe).

    Uses OrcaRouter's OpenAI-compatible /v1/embeddings endpoint — the same
    base URL and key as the LLM, so one key covers the whole pipeline.
    """
    embeddings = await openai_embed(
        texts=texts,
        model=ORCAROUTER_EMBEDDING_MODEL,
        base_url=ORCAROUTER_BASE_URL,
        api_key=_require_orcarouter_api_key(),
    )
    return embeddings.tolist()


class OrcaRouterRAGIntegration:
    """Integration class for OrcaRouter with RAG-Anything."""

    def __init__(self):
        self.base_url = ORCAROUTER_BASE_URL
        self.api_key = ORCAROUTER_API_KEY
        self.model_name = ORCAROUTER_LLM_MODEL
        self.embedding_model = ORCAROUTER_EMBEDDING_MODEL
        self.embedding_dim = ORCAROUTER_EMBEDDING_DIM

        # RAG-Anything configuration
        self.config = RAGAnythingConfig(
            working_dir=f"./rag_storage_orcarouter/{uuid.uuid4()}",
            parser="mineru",
            parse_method="auto",
            enable_image_processing=False,
            enable_table_processing=True,
            enable_equation_processing=True,
        )
        print(f"📁 Using working_dir: {self.config.working_dir}")

        self.rag = None

    async def test_connection(self) -> bool:
        """Best-effort OrcaRouter API key and endpoint check."""
        if not self.api_key:
            print("❌ ORCAROUTER_API_KEY is not set")
            print("   Set it with: export ORCAROUTER_API_KEY=your-api-key")
            return False

        try:
            from openai import AsyncOpenAI

            print(f"🔌 Testing OrcaRouter endpoint at: {self.base_url}")
            client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
            try:
                models = await client.models.list()
            except Exception as model_error:
                print(
                    "⚠️  Could not list OrcaRouter models; continuing because many "
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
                "✅ OrcaRouter API key is configured; chat completion will verify access."
            )
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            print(
                "💡 Check your ORCAROUTER_API_KEY and network access to api.orcarouter.ai"
            )
            return False

    async def test_embedding(self) -> bool:
        """Quick sanity-check for the OrcaRouter embedding endpoint."""
        try:
            print(f"🔢 Testing embedding model: {self.embedding_model}")
            vectors = await embedding_func_async(["hello world"])
            if vectors and len(vectors[0]) > 0:
                print(
                    f"✅ Embedding OK — dim={len(vectors[0])} "
                    f"(configured: {self.embedding_dim})"
                )
                if len(vectors[0]) != self.embedding_dim:
                    print(
                        f"   ⚠️  Dimension mismatch!  Set "
                        f"ORCAROUTER_EMBEDDING_DIM={len(vectors[0])} in your .env"
                    )
                return True
            print("❌ Embedding returned empty vector")
            return False
        except Exception as e:
            print(f"❌ Embedding test failed: {e}")
            return False

    async def test_chat_completion(self) -> bool:
        """Test a basic chat completion with OrcaRouter."""
        try:
            print(f"💬 Testing chat with model: {self.model_name}")
            result = await orcarouter_llm_model_func(
                "Say 'RAG-Anything OrcaRouter integration test passed' in one sentence."
            )
            print("✅ Chat test successful!")
            print(f"   Response: {result.strip()[:120]}")
            return True
        except Exception as e:
            print(f"❌ Chat test failed: {e}")
            return False

    def _make_embedding_func(self) -> EmbeddingFunc:
        return EmbeddingFunc(
            embedding_dim=self.embedding_dim,
            max_token_size=8192,
            func=embedding_func_async,
        )

    async def initialize_rag(self) -> bool:
        """Initialize RAG-Anything with OrcaRouter as the LLM backend."""
        print("\nInitializing RAG-Anything with OrcaRouter ...")
        try:
            self.rag = RAGAnything(
                config=self.config,
                llm_model_func=orcarouter_llm_model_func,
                embedding_func=self._make_embedding_func(),
            )
            print("✅ RAG-Anything initialized successfully!")
            return True
        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            return False

    async def process_document(self, file_path: str):
        """Process a document using OrcaRouter as the LLM backend."""
        if not self.rag:
            print("❌ Call initialize_rag() first")
            return

        print(f"📄 Processing document: {file_path}")
        await self.rag.process_document_complete(
            file_path=file_path,
            output_dir="./output_orcarouter",
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
                    "OrcaRouter Integration with RAG-Anything\n\n"
                    "This integration connects OrcaRouter's model-routing gateway "
                    "with RAG-Anything's multimodal document processing pipeline.\n\n"
                    "Key features:\n"
                    "- One API key routes to 150+ models from OpenAI, Anthropic, Google, "
                    "DeepSeek, Qwen, MiniMax, xAI and more.\n"
                    "- orcarouter/auto: automatic model selection for the best fit.\n"
                    "- openai/text-embedding-3-small: embeddings on the same endpoint.\n"
                    "- OpenAI-compatible API — no SDK changes required.\n"
                    "- Supports text, table, and equation modalities.\n\n"
                    "Configuration:\n"
                    "  ORCAROUTER_API_KEY=sk-orca-your-api-key\n"
                    "  ORCAROUTER_BASE_URL=https://api.orcarouter.ai/v1  (default)\n"
                    "  ORCAROUTER_LLM_MODEL=orcarouter/auto  (default)\n"
                    "  ORCAROUTER_EMBEDDING_MODEL=openai/text-embedding-3-small  (default)\n"
                ),
                "page_idx": 0,
            }
        ]

        print("\nInserting sample content ...")
        await self.rag.insert_content_list(
            content_list=content_list,
            file_path="orcarouter_integration_demo.txt",
            doc_id=f"demo-{uuid.uuid4()}",
            display_stats=True,
        )
        print("✅ Content inserted")

        print("\n🔍 Running sample query ...")
        result = await self.rag.aquery(
            "What models does OrcaRouter route to and what are their characteristics?",
            mode="hybrid",
        )
        print(f"Answer: {result[:400]}")


async def main():
    print("=" * 70)
    print("OrcaRouter + RAG-Anything Integration Example")
    print("=" * 70)

    integration = OrcaRouterRAGIntegration()

    if not await integration.test_connection():
        return False

    print()
    if not await integration.test_embedding():
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
    print("🚀 Starting OrcaRouter integration example ...")
    success = asyncio.run(main())
    exit(0 if success else 1)
