"""
RAG-Anything 文档上传与查询工具
用法: python upload_and_query.py <文件或文件夹路径>
示例: python upload_and_query.py ./docs/
      python upload_and_query.py report.pdf
"""
import asyncio
import os
import sys
import io

# fix Windows GBK encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from functools import partial
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=False)

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc, logger
from raganything import RAGAnything, RAGAnythingConfig

# ---------- 配置 ----------
API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-plus")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMB_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))

# ---------- 初始化 ----------
def create_rag(working_dir: str = "./rag_storage", parser: str = "docling"):
    """创建 RAGAnything 实例"""

    def llm_func(prompt, system_prompt=None, history_messages=[], **kw):
        return openai_complete_if_cache(
            LLM_MODEL, prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=API_KEY, base_url=BASE_URL, **kw,
        )

    def vision_func(prompt, system_prompt=None, history_messages=[],
                    image_data=None, messages=None, **kw):
        """Vision 模型函数，支持图片输入"""
        if messages is not None:
            return openai_complete_if_cache(
                VISION_MODEL, "",
                system_prompt=None, history_messages=[],
                messages=messages, api_key=API_KEY, base_url=BASE_URL, **kw,
            )
        elif image_data is not None:
            return openai_complete_if_cache(
                VISION_MODEL, "",
                system_prompt=None, history_messages=[],
                messages=[
                    {"role": "system", "content": system_prompt} if system_prompt else None,
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}},
                    ]},
                ],
                api_key=API_KEY, base_url=BASE_URL, **kw,
            )
        else:
            return llm_func(prompt, system_prompt, history_messages, **kw)

    embedding_func = EmbeddingFunc(
        embedding_dim=EMB_DIM,
        max_token_size=8192,
        func=partial(openai_embed.func, model=EMB_MODEL, api_key=API_KEY, base_url=BASE_URL),
    )

    config = RAGAnythingConfig(
        working_dir=working_dir,
        parser=parser,
        enable_image_processing=True,
        enable_table_processing=True,
        enable_equation_processing=True,
    )

    return RAGAnything(
        config=config,
        llm_model_func=llm_func,
        vision_model_func=vision_func,
        embedding_func=embedding_func,
    )


async def upload(rag: RAGAnything, path: str, output_dir: str = "./output"):
    """上传单个文件或整个文件夹"""
    target = Path(path)
    if not target.exists():
        print(f"❌ 路径不存在: {path}")
        return

    if target.is_file():
        print(f"\n📄 处理文件: {target.name}")
        await rag.process_document_complete(
            file_path=str(target.absolute()),
            output_dir=output_dir,
        )
        print(f"✅ 完成: {target.name}")

    elif target.is_dir():
        print(f"\n📁 处理文件夹: {target}")
        await rag.process_folder_complete(
            folder_path=str(target.absolute()),
            output_dir=output_dir,
            recursive=True,
        )
        print("✅ 文件夹处理完成")


async def query_loop(rag: RAGAnything):
    """交互式查询"""
    print("\n" + "=" * 50)
    print("  💬 开始查询 (输入 'quit' 退出)")
    print("=" * 50)
    while True:
        try:
            q = input("\n🔍 你的问题: ").strip()
            if q.lower() in ("quit", "exit", "q"):
                break
            if not q:
                continue
            answer = await rag.aquery(q, mode="hybrid")
            print(f"\n🤖 回答:\n{answer}")
        except KeyboardInterrupt:
            break


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("可用的测试文件:")
        print("  - assets/logo.png (图片)")
        print("  - test_doc.txt (文本)")
        print("  - 任意你电脑上的 PDF/Word/图片文件")
        return

    target_path = sys.argv[1]
    rag = create_rag()

    # 初始化
    print("⚙️  初始化中...")
    result = await rag._ensure_lightrag_initialized()
    if not result.get("success"):
        print(f"❌ 初始化失败: {result.get('error')}")
        return
    print("✅ 初始化完成")

    # 上传文档
    await upload(rag, target_path)

    # 进入查询
    await query_loop(rag)

    # 保存
    print("\n💾 保存数据...")
    await rag.finalize_storages()
    print("👋 再见!")


if __name__ == "__main__":
    asyncio.run(main())
