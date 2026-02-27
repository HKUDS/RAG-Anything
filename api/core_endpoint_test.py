import asyncio
import os
import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from raganything import RAGAnything, RAGAnythingConfig
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=".env", override=False)


async def run_test(file_path: str):
    print(f"Starting Integration Test with {file_path}")

    if not os.path.exists(file_path):
        print(f"Dataset not found at: {file_path}")
        return

    print(f"Dataset found: {file_path}")

    # Configuration
    config = RAGAnythingConfig(
        working_dir="./rag_storage_test_core",
        enable_image_processing=False,
        enable_table_processing=True,
        enable_equation_processing=False,
    )

    # API Configuration
    api_key = os.getenv("LLM_BINDING_API_KEY", "lm-studio")
    base_url = os.getenv("LLM_BINDING_HOST", "http://localhost:1234/v1")
    llm_model = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")

    # LLM Function
    def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        return openai_complete_if_cache(
            llm_model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    # Embedding Function
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "768"))
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-embeddinggemma-300m")

    embedding_func = EmbeddingFunc(
        embedding_dim=embedding_dim,
        max_token_size=8192,
        func=lambda texts: openai_embed.func(
            texts,
            model=embedding_model,
            api_key=api_key,
            base_url=base_url,
        ),
    )

    # Initialize RAG
    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        embedding_func=embedding_func,
    )

    # Ensure initialized
    await rag._ensure_lightrag_initialized()
    print("RAG Initialized")

    # Determine processing method based on file extension
    file_ext = os.path.splitext(file_path)[1].lower()

    if file_ext in [".xlsx", ".xls"]:
        print("Processing Excel file...")
        result = await rag.process_excel_file(
            file_path=file_path,
            max_rows=100,
            convert_to_text=True,
            include_summary=True,
        )
    else:
        print(f"Processing Document file ({file_ext})...")
        # For non-excel, use standard process_document
        await rag.process_document_complete(
            file_path=file_path, output_dir="./output_test", parse_method="auto"
        )
        result = {"success": True}  # assume success if no exception

    if isinstance(result, dict) and result.get("success", True):
        print("Processing Successful")
    else:
        print(f"Processing Failed: {result}")
        return

    # Query
    query = "Summarize the key information in this document."
    print(f"\nQuerying: {query}")
    try:
        # Using hybrid mode with default top_k (assuming Qwen model with large context is used)
        response = await rag.aquery(query, mode="hybrid")
        print(f"Answer: {response}")

        if response and len(str(response)) > 10:
            print("Query returned a valid response")
        else:
            print("Query returned empty or short response")

    except Exception as e:
        print(f"Query failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="RAGAnything Core Endpoint Test")
    parser.add_argument("file_path", help="Path to the dataset file")
    args = parser.parse_args()

    asyncio.run(run_test(args.file_path))


if __name__ == "__main__":
    main()
