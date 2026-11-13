"""
Ollama Integration Example with RAG-Anything

This example demonstrates how to integrate Ollama with RAG-Anything for fully
local text and multimodal (VLM) document processing and querying.

Ollama uses a different embedding API (/api/embed) compared to the OpenAI-
compatible /v1/embeddings endpoint, so you cannot simply point the standard
openai_embed helper at an Ollama host.  This example wires up both the LLM
and the embedding function using the ``ollama`` Python library directly, and
provides a vision model adapter for multimodal models (e.g., llama3.2-vision).

Requirements:
- Ollama running locally: https://ollama.com/
- ollama Python package: pip install ollama
- RAG-Anything installed: pip install raganything

Quick start:
    ollama pull llama3.2          # or any chat model you prefer
    ollama pull nomic-embed-text  # embedding model (768-dim)
    ollama pull llama3.2-vision   # optional: for multimodal vision processing
    python examples/ollama_integration_example.py
    # or with multimodal vision enabled:
    python examples/ollama_integration_example.py --multimodal

Environment Setup (optional — defaults shown below):
Create a .env file with:
OLLAMA_HOST=http://localhost:11434
OLLAMA_LLM_MODEL=llama3.2
OLLAMA_VISION_MODEL=llama3.2-vision
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_EMBEDDING_DIM=768
"""

import asyncio
import base64
import os
import sys
import uuid
from typing import Dict, List, Optional, Union

from dotenv import load_dotenv

load_dotenv()

# RAG-Anything imports
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig
from raganything.image_signature import image_mime_type

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3.2")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
OLLAMA_EMBEDDING_DIM = int(os.getenv("OLLAMA_EMBEDDING_DIM", "768"))

# Ollama exposes an OpenAI-compatible chat endpoint at /v1 — reuse the
# existing helper for the LLM side.
OLLAMA_BASE_URL = f"{OLLAMA_HOST}/v1"
OLLAMA_API_KEY = "ollama"  # Ollama ignores the key but the client requires one


async def ollama_llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    **kwargs,
) -> str:
    """Top-level LLM function using Ollama's OpenAI-compatible endpoint."""
    return await openai_complete_if_cache(
        model=OLLAMA_LLM_MODEL,
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        base_url=OLLAMA_BASE_URL,
        api_key=OLLAMA_API_KEY,
        **kwargs,
    )


async def ollama_vision_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: List[Dict] = None,
    image_data: Optional[Union[str, bytes]] = None,
    messages: Optional[List[Dict]] = None,
    **kwargs,
) -> str:
    """Vision model function using Ollama's vision capabilities (#57, #71).

    Supports both single-image multimodal analysis (used during document
    ingestion) and complete message structures (used during VLM queries).
    """
    # If messages format is provided (for multimodal VLM enhanced query), use it directly
    if messages:
        return await openai_complete_if_cache(
            model=OLLAMA_VISION_MODEL,
            prompt="",
            system_prompt=None,
            history_messages=[],
            messages=messages,
            base_url=OLLAMA_BASE_URL,
            api_key=OLLAMA_API_KEY,
            **kwargs,
        )

    # Ingestion single-image analysis format
    if image_data:
        if isinstance(image_data, bytes):
            img_b64 = base64.b64encode(image_data).decode("utf-8")
            raw_bytes = image_data
        elif isinstance(image_data, str):
            if os.path.exists(image_data):
                with open(image_data, "rb") as f:
                    raw_bytes = f.read()
                img_b64 = base64.b64encode(raw_bytes).decode("utf-8")
            else:
                img_b64 = image_data
                raw_bytes = (
                    base64.b64decode(image_data[:24]) if len(image_data) >= 24 else b""
                )
        else:
            raise ValueError("image_data must be a base64 string, bytes, or file path")

        mime_type = image_mime_type(raw_bytes[:24]) or "image/jpeg"
        constructed_messages = []
        if system_prompt:
            constructed_messages.append({"role": "system", "content": system_prompt})
        constructed_messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{img_b64}"},
                    },
                ],
            }
        )
        return await openai_complete_if_cache(
            model=OLLAMA_VISION_MODEL,
            prompt="",
            messages=constructed_messages,
            base_url=OLLAMA_BASE_URL,
            api_key=OLLAMA_API_KEY,
            **kwargs,
        )

    # Text fallback
    return await ollama_llm_model_func(
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        **kwargs,
    )


async def ollama_embedding_async(texts: List[str]) -> List[List[float]]:
    """Top-level embedding function using the native Ollama embed API.

    Unlike the OpenAI-compatible /v1/embeddings endpoint (which Ollama does
    not implement for all models), this calls /api/embed via the ``ollama``
    Python client so it works with any model pulled from the Ollama registry.
    """
    import ollama

    client = ollama.AsyncClient(host=OLLAMA_HOST)
    response = await client.embed(model=OLLAMA_EMBEDDING_MODEL, input=texts)
    return response.embeddings


class OllamaRAGIntegration:
    """Integration class for Ollama with RAG-Anything."""

    def __init__(self, enable_vision: bool = False):
        self.host = OLLAMA_HOST
        self.llm_model = OLLAMA_LLM_MODEL
        self.vision_model = OLLAMA_VISION_MODEL
        self.embedding_model = OLLAMA_EMBEDDING_MODEL
        self.embedding_dim = OLLAMA_EMBEDDING_DIM
        self.enable_vision = enable_vision

        self.config = RAGAnythingConfig(
            working_dir=f"./rag_storage_ollama/{uuid.uuid4()}",
            parser="mineru",
            parse_method="auto",
            enable_image_processing=enable_vision,
            enable_table_processing=True,
            enable_equation_processing=True,
        )
        print(f"📁 Using working_dir: {self.config.working_dir}")
        print(f"🖼️  Multimodal vision enabled: {self.enable_vision}")

        self.rag = None

    async def test_connection(self) -> bool:
        """Verify that Ollama is reachable and the required models are available."""
        try:
            import ollama

            print(f"🔌 Connecting to Ollama at: {self.host}")
            client = ollama.AsyncClient(host=self.host)
            models_response = await client.list()
            available = [m.model for m in models_response.models]

            print(f"✅ Connected! {len(available)} model(s) available")

            required_models = [self.llm_model, self.embedding_model]
            if self.enable_vision:
                required_models.append(self.vision_model)

            for required in required_models:
                # Ollama tags may include ':latest' suffix — check prefix match
                found = any(m.startswith(required.split(":")[0]) for m in available)
                marker = "✅" if found else "⚠️ "
                print(f"  {marker} {required}")
                if not found:
                    print(f"     Run: ollama pull {required}")

            return True
        except ImportError:
            print("❌ ollama package not installed — run: pip install ollama")
            return False
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            print("   Is Ollama running?  Try: ollama serve")
            return False

    async def test_embedding(self) -> bool:
        """Quick sanity-check for the embedding function."""
        try:
            print(f"🔢 Testing embedding model: {self.embedding_model}")
            vectors = await ollama_embedding_async(["hello world"])
            if vectors and len(vectors[0]) > 0:
                print(
                    f"✅ Embedding OK — dim={len(vectors[0])} "
                    f"(configured: {self.embedding_dim})"
                )
                if len(vectors[0]) != self.embedding_dim:
                    print(
                        f"   ⚠️  Dimension mismatch!  Set "
                        f"OLLAMA_EMBEDDING_DIM={len(vectors[0])} in your .env"
                    )
                return True
            print("❌ Embedding returned empty vector")
            return False
        except Exception as e:
            print(f"❌ Embedding test failed: {e}")
            return False

    async def test_chat(self) -> bool:
        """Quick sanity-check for the LLM function."""
        try:
            print(f"💬 Testing LLM model: {self.llm_model}")
            result = await ollama_llm_model_func("Say 'OK' in one word.")
            print(f"✅ Chat OK — response: {result.strip()[:80]}")
            return True
        except Exception as e:
            print(f"❌ Chat test failed: {e}")
            return False

    def _make_embedding_func(self) -> EmbeddingFunc:
        return EmbeddingFunc(
            embedding_dim=self.embedding_dim,
            max_token_size=8192,
            func=ollama_embedding_async,
        )

    async def initialize_rag(self) -> bool:
        """Initialize RAG-Anything with Ollama backends."""
        print("\nInitializing RAG-Anything with Ollama …")
        try:
            self.rag = RAGAnything(
                config=self.config,
                llm_model_func=ollama_llm_model_func,
                vision_model_func=ollama_vision_model_func
                if self.enable_vision
                else None,
                embedding_func=self._make_embedding_func(),
            )
            print("✅ RAG-Anything initialized")
            return True
        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            return False

    async def process_document(self, file_path: str):
        """Process a document with Ollama as the backend."""
        if not self.rag:
            print("❌ Call initialize_rag() first")
            return
        print(f"📄 Processing: {file_path}")
        await self.rag.process_document_complete(
            file_path=file_path,
            output_dir="./output_ollama",
            parse_method="auto",
            display_stats=True,
        )
        print("✅ Processing complete")

    async def simple_query_example(self):
        """Insert sample text and run a demonstration query."""
        if not self.rag:
            print("❌ Call initialize_rag() first")
            return

        content_list = [
            {
                "type": "text",
                "text": (
                    "Ollama Integration with RAG-Anything\n\n"
                    "This integration lets you run a fully local RAG pipeline:\n"
                    "- Ollama serves the LLM via an OpenAI-compatible /v1 endpoint\n"
                    "- Ollama serves embeddings via its native /api/embed endpoint\n"
                    "- Ollama serves vision models (e.g., llama3.2-vision) for multimodal analysis\n"
                    "- RAG-Anything handles document parsing and knowledge-graph construction\n\n"
                    "Popular embedding models: nomic-embed-text (768-dim), "
                    "mxbai-embed-large (1024-dim), all-minilm (384-dim)\n"
                    "Popular chat models: llama3.2, mistral, gemma3, phi4\n"
                    "Popular vision models: llama3.2-vision, qwen2.5-vl, minicpm-v"
                ),
                "page_idx": 0,
            }
        ]

        print("\nInserting sample content …")
        await self.rag.insert_content_list(
            content_list=content_list,
            file_path="ollama_integration_demo.txt",
            doc_id=f"demo-{uuid.uuid4()}",
            display_stats=True,
        )
        print("✅ Content inserted")

        print("\n🔍 Running sample query …")
        result = await self.rag.aquery(
            "What embedding models are recommended for Ollama?",
            mode="hybrid",
        )
        print(f"Answer: {result[:400]}")


async def main():
    enable_vision = any(arg in sys.argv for arg in ("--enable-vision", "--multimodal"))

    print("=" * 70)
    print("Ollama + RAG-Anything Integration Example")
    if enable_vision:
        print("(Multimodal Vision Enabled)")
    print("=" * 70)

    integration = OllamaRAGIntegration(enable_vision=enable_vision)

    if not await integration.test_connection():
        return False

    print()
    if not await integration.test_embedding():
        return False

    print()
    if not await integration.test_chat():
        return False

    print("\n" + "─" * 50)
    if not await integration.initialize_rag():
        return False

    # Uncomment to process a real document:
    # await integration.process_document("path/to/your/document.pdf")

    await integration.simple_query_example()

    print("\n" + "=" * 70)
    print("Example completed successfully!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    print("🚀 Starting Ollama integration example …")
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
