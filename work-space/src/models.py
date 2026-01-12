from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from .config import ENV

def get_model_funcs(provider: str):
    """
    Trả về bộ 3 hàm (LLM, Vision, Embed) tương ứng với provider
    """
    if provider == "openai":
        base_url = None # OpenAI dùng default
        api_key = ENV.openai_api_key
        llm_model = ENV.openai_llm
        vision_model = ENV.openai_vision
        embed_model = ENV.openai_embed
        embed_dim = ENV.openai_dim
    else: # Default Ollama
        base_url = ENV.ollama_base_url
        api_key = ENV.ollama_api_key
        llm_model = ENV.ollama_llm
        vision_model = ENV.ollama_vision
        embed_model = ENV.ollama_embed
        embed_dim = ENV.ollama_dim

    # 1. LLM Function
    async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        return await openai_complete_if_cache(
            model=llm_model,
            prompt=prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=api_key,
            base_url=base_url,
            **kwargs
        )

    # 2. Vision Function
    async def vision_func(prompt, system_prompt=None, history_messages=[], image_data=None, messages=None, **kwargs):
        if messages:
            return await openai_complete_if_cache(
                model=vision_model,
                prompt="",
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs
            )
        # Fallback text-only calls
        return await llm_func(prompt, system_prompt, history_messages, **kwargs)

    # 3. Embedding Function
    embed_func = EmbeddingFunc(
        embedding_dim=embed_dim,
        max_token_size=8192,
        func=lambda texts: openai_embed(
            texts,
            model=embed_model,
            api_key=api_key,
            base_url=base_url,
        ),
    )

    return llm_func, vision_func, embed_func