"""LightRAG configuration and initialization."""

import os
from typing import Optional
import openai
from loguru import logger


def get_openai_embedding_func(api_key: Optional[str] = None):
    """Create OpenAI embedding function for LightRAG."""
    if not api_key:
        api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        logger.warning("No OpenAI API key found, using mock embedding function")
        # Return a mock function for testing
        async def mock_embedding(texts):
            import numpy as np
            return {
                "data": [
                    {"embedding": np.random.randn(1536).tolist()}
                    for _ in texts
                ]
            }
        return mock_embedding
    
    # Set up OpenAI client
    client = openai.AsyncOpenAI(api_key=api_key)
    
    async def openai_embedding(texts):
        """OpenAI embedding function."""
        try:
            response = await client.embeddings.create(
                model="text-embedding-3-small",
                input=texts
            )
            return response
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            raise
    
    return openai_embedding


def get_openai_llm_func(api_key: Optional[str] = None):
    """Create OpenAI LLM function for LightRAG."""
    if not api_key:
        api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        logger.warning("No OpenAI API key found, using mock LLM function")
        # Return a mock function for testing
        async def mock_llm(prompt, **kwargs):
            return f"Mock response for: {prompt[:100]}"
        return mock_llm
    
    # Set up OpenAI client
    client = openai.AsyncOpenAI(api_key=api_key)
    
    async def openai_llm(prompt, **kwargs):
        """OpenAI LLM function."""
        try:
            model = kwargs.get("model", "gpt-4o-mini")
            temperature = kwargs.get("temperature", 0.7)
            max_tokens = kwargs.get("max_tokens", 2000)
            
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM error: {e}")
            raise
    
    return openai_llm


def get_lightrag_config(
    working_dir: str = "./lightrag_storage",
    api_key: Optional[str] = None,
    **kwargs
):
    """Get LightRAG configuration with proper functions."""
    config = {
        "working_dir": working_dir,
        "embedding_func": get_openai_embedding_func(api_key),
        "llm_func": get_openai_llm_func(api_key),
        "chunk_size": kwargs.get("chunk_size", 1000),
        "chunk_overlap": kwargs.get("chunk_overlap", 200),
        "enable_llm_cache": kwargs.get("enable_llm_cache", True),
        **kwargs
    }
    
    # Remove None values
    config = {k: v for k, v in config.items() if v is not None}
    
    return config