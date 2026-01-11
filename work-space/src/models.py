from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from .config import ENV

def get_llm_func():
    async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        return await openai_complete_if_cache(
            model=ENV.llm_model,
            prompt=prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=ENV.ollama_api_key,
            base_url=ENV.ollama_base_url,
            **kwargs
        )
    return llm_func

def get_vision_func():
    base_llm = get_llm_func()
    
    async def vision_func(prompt, system_prompt=None, history_messages=[], image_data=None, messages=None, **kwargs):
        if messages:
            return await openai_complete_if_cache(
                model=ENV.vision_model,
                prompt="",
                messages=messages,
                api_key=ENV.ollama_api_key,
                base_url=ENV.ollama_base_url,
                **kwargs
            )
        return await base_llm(prompt, system_prompt, history_messages, **kwargs)
    return vision_func

def get_embed_func():
    return EmbeddingFunc(
        embedding_dim=ENV.embed_dim,
        max_token_size=8192,
        func=lambda texts: openai_embed(
            texts,
            model=ENV.embed_model,
            api_key=ENV.ollama_api_key,
            base_url=ENV.ollama_base_url,
        ),
    )