"""
独立文件处理 Worker — 每个上传在独立子进程中运行
彻底隔离 LightRAG 实例，避免多 KB 共享 pipeline 状态

用法: python process_worker.py --file=<path> --kb=<name> [--strategy=<name>]
"""
import argparse, asyncio, json, os, sys, io
from pathlib import Path
from functools import partial
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env", override=False)

from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig
from raganything.chunking import build_chunking_func, STRATEGY_META

API_KEY = os.getenv("LLM_BINDING_API_KEY")
BASE_URL = os.getenv("LLM_BINDING_HOST")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMB_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
CHUNKING_STRATEGY = os.getenv("CHUNKING_STRATEGY", "recursive")



# VLM OCR 函数（内嵌，避免跨模块导入 server）
import base64
import pypdfium2 as pdfium
from PIL import Image
import httpx

async def _vlm_ocr_document(file_path: str) -> str:
    """用千问 VL 模型对 PDF/图片做 OCR"""
    try:
        ext = file_path.lower().rsplit(".", 1)[-1] if "." in file_path else ""
        images = []
        if ext == "pdf":
            pdf = pdfium.PdfDocument(file_path)
            for i in range(min(len(pdf), 30)):
                page = pdf[i]
                bitmap = page.render(scale=2)
                img = bitmap.to_pil()
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=70)
                images.append(base64.b64encode(buf.getvalue()).decode())
        elif ext in ("png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif", "webp"):
            img = Image.open(file_path).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            images.append(base64.b64encode(buf.getvalue()).decode())
        else:
            return ""

        all_text = []
        async with httpx.AsyncClient(timeout=120) as client:
            for idx, img_b64 in enumerate(images):
                resp = await client.post(
                    f"{BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    json={
                        "model": os.getenv("VISION_MODEL", "qwen-vl-plus"),
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "请提取图片中的所有文字，保持原有格式。"},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                            ]
                        }],
                        "max_tokens": 2000,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    all_text.append(text)
                else:
                    print(f"[WORKER] VLM OCR 第{idx+1}页失败: {resp.status_code}", flush=True)
        return "\n\n".join(all_text)
    except Exception as e:
        print(f"[WORKER] VLM OCR 异常: {e}", flush=True)
        return ""


PLAIN_TEXT_EXTS = {"txt", "md", "csv", "json", "xml", "yaml", "yml",
                   "py", "js", "ts", "java", "c", "cpp", "h", "html", "css", "log"}


def kb_dir(name: str) -> str:
    return "./rag_storage" if name == "default" else f"./rag_storage_{name}"


def auto_parser(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in ("pdf", "docx", "pptx", "xlsx", "doc", "ppt", "xls", "txt", "md"):
        return "docling"
    if ext in ("png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif", "webp"):
        return "mineru"
    return os.getenv("PARSER", "docling")


def create_rag(parser=None, working_dir=None, chunking_strategy=None):
    if parser is None:
        parser = os.getenv("PARSER", "docling")
    if chunking_strategy is None:
        chunking_strategy = CHUNKING_STRATEGY
    wd = working_dir or os.getenv("WORKING_DIR", "./rag_storage")

    def llm_func(prompt, system_prompt=None, history_messages=None, **kw):
        if "max_tokens" not in kw:
            kw["max_tokens"] = int(os.getenv("MAX_TOKENS", "4096"))
        return openai_complete_if_cache(
            LLM_MODEL, prompt, system_prompt=system_prompt,
            history_messages=history_messages or [], api_key=API_KEY, base_url=BASE_URL, **kw,
        )

    embedding_func = EmbeddingFunc(
        embedding_dim=EMB_DIM, max_token_size=8192,
        func=partial(openai_embed.func, model=EMB_MODEL, api_key=API_KEY, base_url=BASE_URL),
    )

    async def _embed_wrapper(texts):
        return await embedding_func.func(texts, model=EMB_MODEL)

    async def _llm_wrapper(prompt, system_prompt="", history_messages=None, **kw):
        return await llm_func(prompt, system_prompt=system_prompt,
                              history_messages=history_messages or [], **kw)

    chunking_map = {
        "fixed_size": None,
        "recursive": __import__("raganything.chunking", fromlist=["recursive_chunking"]).recursive_chunking,
        "sentence": __import__("raganything.chunking", fromlist=["sentence_chunking"]).sentence_chunking,
        "structure": __import__("raganything.chunking", fromlist=["structure_chunking"]).structure_chunking,
        "semantic": __import__("raganything.chunking", fromlist=["make_semantic_chunking"]).make_semantic_chunking(_embed_wrapper),
        "agentic": __import__("raganything.chunking", fromlist=["make_agentic_chunking"]).make_agentic_chunking(_llm_wrapper, LLM_MODEL),
    }
    chosen = chunking_map.get(chunking_strategy)

    lightrag_kwargs = {
        "chunk_token_size": int(os.getenv("CHUNK_SIZE", "800")),
        "chunk_overlap_token_size": int(os.getenv("CHUNK_OVERLAP", "100")),
    }
    if chosen is not None:
        lightrag_kwargs["chunking_func"] = chosen

    config = RAGAnythingConfig(
        working_dir=wd, parser=parser,
        enable_image_processing=os.getenv("ENABLE_IMAGE_PROCESSING", "false").lower() == "true",
        enable_table_processing=os.getenv("ENABLE_TABLE_PROCESSING", "false").lower() == "true",
        enable_equation_processing=os.getenv("ENABLE_EQUATION_PROCESSING", "false").lower() == "true",
    )
    return RAGAnything(config=config, llm_model_func=llm_func,
                       embedding_func=embedding_func, lightrag_kwargs=lightrag_kwargs)


async def process_file(file_path: str, kb_name: str, chunking_strategy: str = ""):
    """处理单个文件并写入对应 KB 目录"""
    filename = os.path.basename(file_path)
    target_dir = kb_dir(kb_name)
    strategy = chunking_strategy or CHUNKING_STRATEGY
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    merge_failed = False  # Track merging/extraction failures

    strategy_name = STRATEGY_META.get(strategy, {}).get("name", strategy)
    print(f"[WORKER] 开始处理: file={filename} kb={kb_name} dir={target_dir} strategy={strategy_name}", flush=True)

    # 创建 RAG 实例
    rag = create_rag(working_dir=target_dir, chunking_strategy=strategy)
    await rag._ensure_lightrag_initialized()

    safe_path = str(Path(file_path).resolve())

    if ext in PLAIN_TEXT_EXTS:
        print(f"[WORKER] 纯文本模式，直接读取", flush=True)
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text_content = f.read()
        if text_content.strip():
            await rag.insert_content_list(
                [{"type": "text", "text": text_content, "page_idx": 0}],
                file_path=filename
            )
    else:
        output_dir = f"./output_{kb_name}" if kb_name != "default" else "./output"
        docling_ok = False
        try:
            await rag.process_document_complete(safe_path, output_dir=output_dir)
            docling_ok = True
        except Exception as e:
            err_msg = str(e)
            print(f"[WORKER] Docling 处理失败: {err_msg[:150]}", flush=True)
            # "Separator is not found" 错误：PDF 文本是大段连续内容，手动分行后重试
            if "Separator is not found" in err_msg or "chunk exceed" in err_msg:
                print(f"[WORKER] 检测到大段连续文本，尝试预处理后重试...", flush=True)
                try:
                    # 读取 PDF 文本内容，每隔 400 字符插入换行
                    with open(safe_path, "rb") as f:
                        raw = f.read()
                    # 尝试读取已解析的文本
                    import glob as _glob
                    md_files = _glob.glob(f"{output_dir}/**/*.md", recursive=True)
                    if md_files:
                        for mf in md_files[:3]:
                            with open(mf, "r", encoding="utf-8", errors="replace") as f:
                                text = f.read()
                            # 插入段落分隔符
                            text = text.replace("。", "。\n\n").replace(". ", ".\n\n")
                            # 长行强制换行
                            lines = text.split("\n")
                            new_lines = []
                            for line in lines:
                                if len(line) > 400:
                                    for i in range(0, len(line), 400):
                                        new_lines.append(line[i:i+400])
                                else:
                                    new_lines.append(line)
                            with open(mf, "w", encoding="utf-8") as f:
                                f.write("\n".join(new_lines))
                        print(f"[WORKER] 预处理完成，重试中...", flush=True)
                        await rag.process_document_complete(safe_path, output_dir=output_dir)
                        docling_ok = True
                    else:
                        print(f"[WORKER] 未找到解析输出文件，使用 VLM OCR 兜底", flush=True)
                except Exception as e2:
                    print(f"[WORKER] 预处理失败: {e2}，使用 VLM OCR 兜底", flush=True)

        # VLM OCR 兜底（Docling 失败或产生 0 chunk 时触发）
        if ext in ("pdf", "doc", "png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif", "webp"):
            chunks_ok = False
            sp = Path(target_dir) / "kv_store_doc_status.json"
            if sp.exists():
                with open(sp, "r", encoding="utf-8") as f:
                    ds = json.load(f)
                for did, info in ds.items():
                    if info.get("file_path") == filename:
                        if info.get("chunks_count", 0) > 0:
                            chunks_ok = True
                        break
            if not docling_ok or not chunks_ok:
                print(f"[WORKER] VLM OCR 兜底: {filename}", flush=True)
                try:
                    ocr_text = await _vlm_ocr_document(file_path)
                    if ocr_text.strip():
                        await rag.insert_content_list(
                            [{"type": "text", "text": ocr_text, "page_idx": 0}],
                            file_path=filename
                        )
                        print(f"[WORKER] VLM OCR 完成: {len(ocr_text)} 字符", flush=True)
                except Exception as e2:
                    print(f"[WORKER] VLM OCR 失败: {e2}", flush=True)
                    raise

    await rag.finalize_storages()

    # Verify that chunks were actually created — if the merging/extraction
    # stage failed silently, the document status will report zero chunks.
    sp = Path(target_dir) / "kv_store_doc_status.json"
    if sp.exists():
        with open(sp, "r", encoding="utf-8") as f:
            ds = json.load(f)
        found = False
        for did, info in ds.items():
            if info.get("file_path") == filename:
                found = True
                if info.get("chunks_count", 0) == 0 and not info.get("status") == "failed":
                    merge_failed = True
                    print(
                        f"[WORKER] ERROR: 文档处理完成但 chunks=0, "
                        f"可能是合并(merging)/实体提取步骤失败. "
                        f"doc_id={did} status={info.get('status')}",
                        flush=True,
                    )
                break
        if not found:
            print(f"[WORKER] WARNING: 文档记录未在 doc_status 中找到: {filename}", flush=True)

    if merge_failed:
        print(f"[WORKER] 失败 (合并阶段错误): {filename}", flush=True)
        sys.exit(1)

    print(f"[WORKER] 完成: {filename}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--strategy", default="")
    args = parser.parse_args()

    asyncio.run(process_file(args.file, args.kb, args.strategy))
