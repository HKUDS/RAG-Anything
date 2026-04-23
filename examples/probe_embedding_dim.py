from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv


def _get_env(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    return v


async def main() -> None:
    load_dotenv(".env", override=False)

    binding = _get_env("EMBEDDING_BINDING").lower() or "openai_compatible"
    model = _get_env("EMBEDDING_MODEL")

    if binding == "dashscope_mm":
        model = model or "tongyi-embedding-vision-flash-2026-03-06"
        api_key = (
            _get_env("DASHSCOPE_API_KEY")
            or _get_env("LLM_BINDING_API_KEY")
            or _get_env("OPENAI_API_KEY")
        )
        if not api_key:
            raise SystemExit(
                "Missing required config: DASHSCOPE_API_KEY (or LLM_BINDING_API_KEY / OPENAI_API_KEY)."
            )

        def _call_dashscope():
            import dashscope

            dashscope.api_key = api_key
            return dashscope.MultiModalEmbedding.call(
                model=model,
                input=[{"text": "hello"}],
            )

        resp = await asyncio.to_thread(_call_dashscope)
        status_code = getattr(resp, "status_code", None)
        output = getattr(resp, "output", None)
        if status_code not in (None, 200):
            raise SystemExit(f"DashScope embedding failed: {resp}")

        items = getattr(output, "embeddings", None)
        if items is None and isinstance(output, dict):
            items = output.get("embeddings")
        if not items:
            raise SystemExit(f"No embeddings found in response: {resp}")

        first = items[0]
        vec = getattr(first, "embedding", None)
        if vec is None and isinstance(first, dict):
            vec = first.get("embedding")
        if not vec:
            raise SystemExit(f"No vector found in first embedding item: {first}")

        print("embedding_binding=dashscope_mm")
        print(f"embedding_model={model}")
        print(f"embedding_dim={len(vec)}")
        return

    model = model or "text-embedding-v3"
    base_url = _get_env("LLM_BINDING_HOST") or _get_env("OPENAI_BASE_URL")
    api_key = _get_env("LLM_BINDING_API_KEY") or _get_env("OPENAI_API_KEY")

    missing = [k for k, v in {"base_url": base_url, "api_key": api_key}.items() if not v]
    if missing:
        raise SystemExit(
            "Missing required config in environment/.env: "
            + ", ".join(missing)
            + "\nPlease set LLM_BINDING_HOST + LLM_BINDING_API_KEY (or OPENAI_BASE_URL + OPENAI_API_KEY)."
        )

    from lightrag.llm.openai import openai_embed

    emb = await openai_embed(
        texts=["hello"],
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    vec = emb[0]
    print("embedding_binding=openai_compatible")
    print(f"embedding_model={model}")
    print(f"embedding_dim={len(vec)}")


if __name__ == "__main__":
    asyncio.run(main())

