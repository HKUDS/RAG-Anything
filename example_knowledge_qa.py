#!/usr/bin/env python3
"""
RAG-Anything 知识库智能客服示例
用于处理 PDF 文档并回答用户问题
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from raganything import RAGAnything, RAGAnythingConfig
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc

# 加载环境变量
load_dotenv()

# 配置参数
API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
WORKING_DIR = os.getenv("WORKING_DIR", "./rag_storage")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./output")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "3072"))
PARSER = os.getenv("PARSER", "mineru")


def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
    """LLM 模型函数 - 用于生成回答"""
    return openai_complete_if_cache(
        LLM_MODEL,
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        api_key=API_KEY,
        base_url=BASE_URL,
        **kwargs,
    )


def vision_model_func(
    prompt, system_prompt=None, history_messages=[], image_data=None, messages=None, **kwargs
):
    """视觉模型函数 - 用于分析图像内容"""
    if messages:
        return openai_complete_if_cache(
            VISION_MODEL,
            "",
            system_prompt=None,
            history_messages=[],
            messages=messages,
            api_key=API_KEY,
            base_url=BASE_URL,
            **kwargs,
        )
    elif image_data:
        return openai_complete_if_cache(
            VISION_MODEL,
            "",
            system_prompt=None,
            history_messages=[],
            messages=[
                {"role": "system", "content": system_prompt} if system_prompt else None,
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                        },
                    ],
                }
                if image_data
                else {"role": "user", "content": prompt},
            ],
            api_key=API_KEY,
            base_url=BASE_URL,
            **kwargs,
        )
    else:
        return llm_model_func(prompt, system_prompt, history_messages, **kwargs)


embedding_func = EmbeddingFunc(
    embedding_dim=EMBEDDING_DIM,
    max_token_size=8192,
    func=lambda texts: openai_embed.func(
        texts,
        model=EMBEDDING_MODEL,
        api_key=API_KEY,
        base_url=BASE_URL,
    ),
)


async def initialize_rag():
    """初始化 RAG 系统"""
    config = RAGAnythingConfig(
        working_dir=WORKING_DIR,
        parser=PARSER,
        parse_method="auto",
        enable_image_processing=True,
        enable_table_processing=True,
        enable_equation_processing=True,
    )

    rag = RAGAnything(
        config=config,
        llm_model_func=llm_model_func,
        vision_model_func=vision_model_func,
        embedding_func=embedding_func,
    )

    # Ensure LightRAG is initialized so aquery() works without processing first
    await rag._ensure_lightrag_initialized()

    return rag


async def process_document(rag, file_path: str):
    """处理单个文档"""
    print(f"📄 正在处理文档: {file_path}")
    
    output_path = Path(OUTPUT_DIR) / Path(file_path).stem
    output_path.mkdir(parents=True, exist_ok=True)
    
    await rag.process_document_complete(
        file_path=file_path,
        output_dir=str(output_path),
        parse_method="auto",
        display_stats=True
    )
    print(f"✅ 文档处理完成！输出目录: {output_path}")


async def query_knowledge_base(rag, question: str):
    """查询知识库"""
    print(f"\n❓ 问题: {question}")
    
    # 纯文本查询
    result = await rag.aquery(question, mode="hybrid")
    print(f"\n💡 回答:\n{result}")
    return result


async def main():
    """主函数"""
    print("=" * 60)
    print("RAG-Anything 知识库智能客服")
    print("=" * 60)
    
    # 检查 API Key
    if not API_KEY:
        print("❌ 错误: 请在 .env 文件中设置 OPENAI_API_KEY")
        return
    
    # 初始化 RAG
    print("\n🔧 初始化 RAG 系统...")
    rag = await initialize_rag()
    print("✅ RAG 系统初始化完成！")
    
    # 创建示例文件夹
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    Path(WORKING_DIR).mkdir(exist_ok=True)
    
    # 示例用法
    print("\n" + "=" * 60)
    print("使用说明:")
    print("1. 将 PDF 文档放入 ./documents 目录")
    print("2. 修改下面的 documents_folder 变量")
    print("3. 运行 python example_knowledge_qa.py --process 批量处理文档")
    print("4. 运行 python example_knowledge_qa.py --query '问题' 进行问答")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--process":
            # 处理文档模式
            asyncio.run(main())
            # 处理命令行指定的文件
            if len(sys.argv) > 2:
                file_path = sys.argv[2]
                rag = asyncio.run(initialize_rag())
                asyncio.run(process_document(rag, file_path))
        elif sys.argv[1] == "--query":
            # 查询模式
            if len(sys.argv) > 2:
                question = " ".join(sys.argv[2:])
                rag = asyncio.run(initialize_rag())
                asyncio.run(query_knowledge_base(rag, question))
        else:
            print("用法:")
            print("  python example_knowledge_qa.py --process <文件路径>  处理文档")
            print("  python example_knowledge_qa.py --query <问题>       查询知识库")
    else:
        asyncio.run(main())
