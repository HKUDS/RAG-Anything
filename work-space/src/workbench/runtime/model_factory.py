import re
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from src.config import ENV

try:
    from src.gliner_handler import gliner_service
    from src.prompts import HYBRID_RELATION_PROMPT
except ImportError:
    gliner_service = None
    HYBRID_RELATION_PROMPT = ""


def get_model_funcs(provider: str, use_gliner: bool = False, gliner_labels: list = None):
    if provider == "openai":
        base_url = None
        api_key = ENV.openai_api_key
        llm_model = ENV.openai_llm
        vision_model = ENV.openai_vision
        embed_model = ENV.openai_embed
        embed_dim = ENV.openai_dim
    else:
        base_url = ENV.ollama_base_url
        api_key = ENV.ollama_api_key
        llm_model = ENV.ollama_llm
        vision_model = ENV.ollama_vision
        embed_model = ENV.ollama_embed
        embed_dim = ENV.ollama_dim

    async def base_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
        return await openai_complete_if_cache(
            model=llm_model,
            prompt=prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    if use_gliner and gliner_service:
        gliner_service.load_model()

        async def wrapped_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
            match = re.search(r"-Data-\s*(.*)", prompt, re.DOTALL)
            if match:
                raw_text = match.group(1).strip()
                labels = gliner_labels or ["Disease", "Medication"]
                entities_str = gliner_service.extract(raw_text, labels)
                new_prompt = HYBRID_RELATION_PROMPT.format(
                    input_text=raw_text,
                    pre_extracted_entities=entities_str,
                )
                return await base_llm_func(new_prompt, system_prompt, history_messages, **kwargs)
            return await base_llm_func(prompt, system_prompt, history_messages, **kwargs)

        final_llm_func = wrapped_llm_func
    else:
        final_llm_func = base_llm_func

    async def vision_func(prompt, system_prompt=None, history_messages=[], image_data=None, messages=None, **kwargs):
        if messages:
            return await openai_complete_if_cache(
                model=vision_model,
                prompt="",
                messages=messages,
                api_key=api_key,
                base_url=base_url,
                **kwargs,
            )
        return await final_llm_func(prompt, system_prompt, history_messages, **kwargs)

    embed_func = EmbeddingFunc(
        embedding_dim=embed_dim,
        max_token_size=8192,
        func=lambda texts: openai_embed.func(
            texts,
            model=embed_model,
            api_key=api_key,
            base_url=base_url,
        ),
    )

    return final_llm_func, vision_func, embed_func
