#!/usr/bin/env python
"""
Excel Integration Example with RAGAnything

This example shows how to integrate your existing pandas Excel workflow
with RAGAnything for intelligent querying and analysis.
"""

import os
import argparse
import asyncio
import pandas as pd
from pathlib import Path
import sys

# Add project root directory to Python path
sys.path.append(str(Path(__file__).parent.parent))

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=False)


async def example_pandas_integration(excel_file_path: str):
    """
    Example showing how to integrate your existing pandas workflow with RAGAnything

    This replicates your existing code pattern:
    1. Load Excel data with pandas
    2. Limit data (head(500))
    3. Process with RAGAnything for intelligent querying
    """

    # Your existing pandas workflow
    print("📊 Loading Excel data with pandas...")

    def load_data():
        df = pd.read_excel(excel_file_path)
        return df

    # Running function
    data = load_data()
    print(f"Original data shape: {data.shape}")
    print("Data preview:")
    print(data.head())

    # Limiting the data (as in your example)
    limited_data = data.head(500)
    print(f"Limited data shape: {limited_data.shape}")

    # Convert DataFrame to JSON (as in your example)
    data_json = limited_data.to_json(orient="records")
    print(f"JSON data length: {len(data_json)} characters")

    # Now integrate with RAGAnything
    print("\n🤖 Setting up RAGAnything...")

    # Create RAGAnything configuration
    config = RAGAnythingConfig(
        working_dir="./rag_storage_excel",
        parser="mineru",  # We won't use document parsing for Excel
        parse_method="auto",
        enable_image_processing=False,  # Not needed for Excel data
        enable_table_processing=True,  # Good for structured data
        enable_equation_processing=False,
    )

    # Get API configuration
    api_key = os.getenv("LLM_BINDING_API_KEY", "lm-studio")
    base_url = os.getenv("LLM_BINDING_HOST", "http://localhost:1234/v1")

    # Define LLM model function for LM Studio
    def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        model_name = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")

        # Filter out parameters that LM Studio doesn't support
        call_kwargs = dict(kwargs)
        lmstudio_incompatible_params = [
            "stream",
            "stream_options",
            "parallel_tool_calls",
        ]
        for param in lmstudio_incompatible_params:
            call_kwargs.pop(param, None)

        return openai_complete_if_cache(
            model_name,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=api_key,
            base_url=base_url,
            **call_kwargs,
        )

    # Define embedding function for LM Studio
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-embeddinggemma-300m")
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "768"))
    embedding_base_url = os.getenv("EMBEDDING_BINDING_HOST", base_url)
    embedding_api_key = os.getenv("EMBEDDING_BINDING_API_KEY", api_key)
    max_token_size = int(os.getenv("MAX_EMBED_TOKENS", "8192"))
    embedding_func = EmbeddingFunc(
        embedding_dim=embedding_dim,
        max_token_size=max_token_size,
        func=lambda texts: openai_embed(
            texts,
            model=embedding_model,
            api_key=embedding_api_key,
            base_url=embedding_base_url,
        ),
    )

    # Initialize RAGAnything
    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        embedding_func=embedding_func,
    )

    print("🔄 Processing Excel data with RAGAnything...")

    # Method 1: Process DataFrame directly (recommended for your workflow)
    result = await rag.process_dataframe(
        df=limited_data,
        doc_id="hotel_bookings_limited",
        convert_to_text=True,  # Convert to natural language
        include_summary=True,  # Include dataset summary
        chunk_size=50,  # Process in smaller chunks
    )

    if result["success"]:
        print(f"✅ Successfully processed {result['total_rows']} rows")
        print(f"📋 Columns: {', '.join(result['columns'])}")
        print(f"🔗 Created {result['chunks_created']} text chunks")
    else:
        print(f"❌ Error processing data: {result['error']}")
        return

    # Now you can query your Excel data with natural language!
    print("\n🔍 Querying your Excel data...")

    # Example queries for hotel booking data (adjust based on your actual data)
    queries = [
        "What are the key statistical trends in this dataset?",
        "Which columns have the highest variance or most missing values?",
        "Can you identify any outliers or anomalies in the data?",
        "What actionable insights can be drawn from this dataset for medical decisions?",
    ]

    for query in queries:
        print(f"\n❓ Query: {query}")
        try:
            answer = await rag.aquery(query, mode="hybrid")
            print(f"💬 Answer: {answer}")
        except Exception as e:
            print(f"❌ Error querying: {str(e)}")

    print("\n✨ Excel integration complete!")


async def method_2_file_based(excel_file_path: str):
    """
    Alternative method: Process Excel file directly without loading into pandas first
    """
    print("\n📂 Method 2: Direct file processing...")

    # Setup RAGAnything (same as above)
    config = RAGAnythingConfig(
        working_dir="./rag_storage_excel_method2",
        enable_image_processing=False,
        enable_table_processing=True,
        enable_equation_processing=False,
    )

    api_key = os.getenv("LLM_BINDING_API_KEY", "lm-studio")
    base_url = os.getenv("LLM_BINDING_HOST", "http://localhost:1234/v1")

    def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        model_name = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
        call_kwargs = dict(kwargs)
        lmstudio_incompatible_params = [
            "stream",
            "stream_options",
            "parallel_tool_calls",
        ]
        for param in lmstudio_incompatible_params:
            call_kwargs.pop(param, None)

        return openai_complete_if_cache(
            model_name,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=api_key,
            base_url=base_url,
            **call_kwargs,
        )

    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-embeddinggemma-300m")
    embedding_dim = int(os.getenv("EMBEDDING_DIM", "768"))
    max_token_size = int(os.getenv("MAX_EMBED_TOKENS", "8192"))
    embedding_func = EmbeddingFunc(
        embedding_dim=embedding_dim,
        max_token_size=max_token_size,
        func=lambda texts: openai_embed(
            texts,
            model=embedding_model,
            api_key=api_key,
            base_url=base_url,
        ),
    )

    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        embedding_func=embedding_func,
    )

    # Process Excel file directly
    result = await rag.process_excel_file(
        file_path=excel_file_path,
        max_rows=500,  # Like your head(500)
        convert_to_text=True,
        include_summary=True,
    )

    if result["success"]:
        print(
            f"✅ Processed Excel file: {result['total_rows']} rows, {result['chunks_created']} chunks"
        )

        # Query the data
        answer = await rag.aquery(
            "What is this data about and what insights can you provide?"
        )
        print(f"💬 Answer: {answer}")
    else:
        print(f"❌ Error: {result['error']}")


def main():
    """Main function to run the Excel integration example"""
    parser = argparse.ArgumentParser(description="Excel Integration with RAGAnything")
    parser.add_argument("excel_file", help="Path to the Excel file to process")
    parser.add_argument(
        "--method",
        choices=["dataframe", "file", "both"],
        default="dataframe",
        help="Processing method: dataframe (pandas first), file (direct), or both",
    )

    args = parser.parse_args()

    # Check if file exists
    if not os.path.exists(args.excel_file):
        print(f"❌ Error: Excel file '{args.excel_file}' not found")
        return

    print("🚀 RAGAnything Excel Integration Example")
    print(f"📁 Processing file: {args.excel_file}")
    print("=" * 50)

    if args.method in ["dataframe", "both"]:
        print("🐼 Method 1: Pandas DataFrame Integration")
        asyncio.run(example_pandas_integration(args.excel_file))

    if args.method in ["file", "both"]:
        print("\n" + "=" * 50)
        asyncio.run(method_2_file_based(args.excel_file))


if __name__ == "__main__":
    main()
