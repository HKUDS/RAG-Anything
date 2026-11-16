# Model, parser and ingestion options

## Existing LightRAG instances

`RAGAnything(lightrag=existing_rag)` inherits that instance's LLM and embedding
functions. Explicit `llm_model_func` and `embedding_func` arguments take priority.
Provide a separate `vision_model_func` when the inherited model cannot accept
images. Requesting an image/table/equation/generic description without a callable
model raises a configuration error; it does not mark raw metadata as a successful
model description. `check_mineru_installation()` remains a deprecated alias for
`check_parser_installation()`.

## ASR

`RAGAnythingConfig(asr_mode="local")` keeps faster-whisper as the default.
`asr_model` and `asr_language` select the model and language. The existing
`WHISPER_MODEL` and `WHISPER_LANGUAGE` environment variables remain supported.

For `asr_mode="online"`, configure `asr_base_url`, `asr_model` and supply
`asr_api_key` at runtime. This calls an OpenAI-compatible
`/audio/transcriptions` endpoint requesting `verbose_json`; the endpoint must
return a JSON transcription containing `text` or `segments`. A model with only
plain JSON/text support needs a custom adapter. Online ASR does not require
faster-whisper. Video still needs its scene and media dependencies.

```python
async def transcribe(audio_path, language=None, model=None):
    return [{"start": 0.0, "end": 2.5, "text": "Revenue is 42."}]

rag = RAGAnything(
    config=RAGAnythingConfig(asr_mode="custom", enable_audio_processing=True),
    asr_model_func=transcribe,
    llm_model_func=llm,
    embedding_func=embeddings,
)
```

Custom callbacks can be sync or async. Async callbacks execute on the caller's
event loop. Direct processor users should await `atranscribe()` in async code.
Audio and video share these ASR settings. Environment equivalents are
`ASR_MODE`, `ASR_MODEL`, `ASR_LANGUAGE`, `ASR_BASE_URL`, and `ASR_API_KEY`.

## Remote MinerU and preprocessed output

Configure `mineru_backend`, `mineru_vlm_url` and `mineru_source` on
`RAGAnythingConfig`, or use `MINERU_BACKEND`, `MINERU_VLM_URL`, `MINERU_SOURCE`.
Explicit parsing kwargs override these defaults. Cache identity includes the
backend options and hashes the VLM URL. MinerU 3.x remains required; these options
do not enable MinerU 4.x.

```python
content, doc_id = await rag.process_preprocessed_output(
    "/data/mineru/report/auto", file_stem="report", file_path="report.pdf"
)
results = await rag.process_preprocessed_directory(
    "/data/mineru", concurrency=2, continue_on_error=False
)
```

This reads MinerU legacy/v2 JSON and resolves its media paths without rerunning
MinerU. Pass a bundle root, document directory or backend directory. A directory
containing multiple documents requires an explicit `file_stem`; multiple matching
backends require a specific output directory. Batch mode expects one document per
subdirectory. Imported output remains caller-owned: deleting the RAG index does
not delete these original files. Keep imported media available for VLM queries;
use `extra_safe_dirs` when they lie outside the configured parser output area.

## Cross-page tables

`merge_continued_tables=True` (`MERGE_CONTINUED_TABLES=true`) opts into merging
adjacent-page table fragments with matching columns and an explicit continuation
caption/label. Same-page, unlabelled and conflicting numbered tables stay separate.
The result retains `page_idx`, `page_idx_end` and source images in `table_img_paths`.
Changing this setting invalidates the parse cache. The default is `False`.

## Private prompt templates

```python
config = RAGAnythingConfig(
    prompt_language="zh",
    custom_prompts={"TABLE_ANALYSIS_SYSTEM": "You analyze financial statements."},
)
rag = RAGAnything(config=config, llm_model_func=llm, embedding_func=embeddings)
rag.update_prompts({"TABLE_ANALYSIS_SYSTEM": "Use the supplied accounting definitions."})
```

The language and overrides belong to this instance and reach its processors,
chunk templates and queries. They do not change other instances. With no explicit
language, the instance follows the process-global prompt registry. The existing
module-level `set_prompt_language()` and `update_prompts()` remain process-global.
Templates retain the format fields expected by their original template; context
processing may select a separate `*_with_context` template.

## Retrieved multimodal references

```python
result = await rag.aquery("What changed?", return_multimodal_context=True)
answer = result["response"]
assets = result["multimodal_context"]  # [{"type": "image", "path": "..."}, ...]
```

By default queries still return a string or async iterator. With this flag they
return a dictionary, including when `stream=True`: iterate `result["response"]`.
References come from retrieved context, not paths generated in the answer. They
list retrieved assets rather than proving which facts the answer uses. Text-only
queries request a retrieval prompt in addition to the answer, so this opt-in adds
retrieval work. VLM queries reuse their retrieval prompt. Commas, `#`, spaces and
JSON-escaped characters in paths are preserved. Bypass queries have no references.

The Ollama example supports `--multimodal` and `OLLAMA_VISION_MODEL`, sending
images through Ollama's OpenAI-compatible chat endpoint. Embeddings still use the
native Ollama embedding API. See [container usage](docker_deployment.md) for the
optional CPU batch image.

# 模型、解析与导入配置

传入已有 `LightRAG` 时，RAG-Anything 会继承它的 LLM 和向量函数；显式传入的函数
优先。已有文本模型不能看图时，仍应单独提供 `vision_model_func`。缺少可调用模型
时，图片、表格、公式及通用内容的描述生成会明确报错，不会把原始元数据当成完成
的模型分析。旧 `check_mineru_installation()` 接口作为弃用别名保留。

音频默认仍为本地 faster-whisper。`asr_mode="online"` 需要运行时提供端点、模型和
凭据，端点应支持 `/audio/transcriptions` 的 `verbose_json` 响应。只支持其他响应
格式的服务请使用自定义适配器。`asr_mode="custom"` 配合 `asr_model_func` 支持同步
和异步转写函数；异步函数在调用方事件循环中执行。直接使用处理器时，在异步代码
中调用 `await processor.atranscribe(...)`。音视频共用这些设置；视频在线转写仍需
安装场景识别、媒体处理依赖。配置字段和对应环境变量见上文。

远程 MinerU 可配置 `mineru_backend`、`mineru_vlm_url`、`mineru_source`，单次解析参数
优先于配置，缓存会区分这些选项。仍只支持 MinerU 3.x。已有 MinerU 结果可通过
`process_preprocessed_output()` 或 `process_preprocessed_directory()` 直接导入，
不用重新 OCR。单目录包含多个文档时必须指定 `file_stem`，多个后端结果同时匹配时
需要指定具体目录；批量导入要求每个子目录对应一个文档。外部导入文件仍归调用方
管理，删除索引不会删除这些原始文件。VLM 查询仍需保留媒体文件，并按需传入
`extra_safe_dirs`。

跨页表格合并默认关闭。启用后只合并相邻页、有明确续表标记且列数匹配的表格，
保留起止页码及各页图片路径。同页表格、无标记表格和编号冲突的表格不会合并；
切换开关会使原解析缓存失效。

`prompt_language` 和 `custom_prompts` 对当前实例生效，并用于实际处理器、chunk
模板和查询；不会污染其他实例。未指定语言时沿用全局提示词设置。模块级语言切换
和 `update_prompts()` 仍然影响全局。修改模板时保留其所需的格式字段；启用上下文
时还可能使用单独的 `*_with_context` 模板。

查询默认返回类型不变。显式设置 `return_multimodal_context=True` 后返回字典，
流式答案位于 `result["response"]`；素材引用来自检索上下文，不依赖模型在答案中
输出路径。这些引用表示检索到了哪些素材，不代表逐条事实证明。普通文本查询会多
获取一次检索提示词，因此有额外检索开销；VLM 查询复用已有提示词。路径中的逗号、
井号、空格及 JSON 转义均会保留，bypass 模式没有检索引用。

Ollama 示例的 `--multimodal` 会使用 `OLLAMA_VISION_MODEL`，通过兼容 OpenAI 的
聊天接口传图，向量仍走 Ollama 原生接口。容器运行方式见[容器文档](docker_deployment.md)。

## Opt-in body budgets / 显式内容预算

`max_table_tokens=0` and `max_modal_content_tokens=0` disable truncation by default.
Set a positive value (or `MAX_TABLE_TOKENS` / `MAX_MODAL_CONTENT_TOKENS`) to limit
only the table/formula body sent for model description. Other prompt/context text
still consumes tokens. Counts use LightRAG's configured tokenizer (or a character
estimate when unavailable). Counting includes omission markers; table headers and
complete rows are preserved. A budget too small for required structure raises
`TokenBudgetError`. Original content in stored chunks remains complete.

默认两个预算均为 `0`，不截断。显式设置正数后才限制发给描述模型的表格或公式正文，
省略标记也计入预算；提示词和上下文另占 tokens。表格保留完整表头及行，预算不足以
容纳必要结构时会明确报错。入库 chunk 仍保留原始完整内容。
