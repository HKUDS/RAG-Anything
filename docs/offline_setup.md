# 在离线环境中运行 RAG-Anything

本文档解释了在没有互联网访问的环境中运行 RAG-Anything 项目的关键注意事项。

## 网络依赖：`LightRAG` 和 `tiktoken`

`RAGAnything` 核心引擎依赖于 `LightRAG` 库来实现其主要功能。而 `LightRAG` 反过来使用 OpenAI 的 `tiktoken` 库进行文本分词。

默认情况下，`tiktoken` 库具有网络依赖性。在首次使用时，它会尝试从 OpenAI 的公共服务器（`openaipublic.blob.core.windows.net`）下载分词器模型。如果应用程序在离线或网络受限的环境中运行，此下载将失败，导致 `LightRAG` 实例初始化失败。

这会导致类似以下的错误：

```
Failed to initialize LightRAG instance: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/o200k_ba
```

此依赖性是间接的。`RAG-Anything` 代码库本身不直接导入或调用 `tiktoken`。该调用是从 `lightrag` 库内部进行的。

## 解决方案：使用本地 `tiktoken` 缓存

要解决此问题并实现完全离线操作，您必须为 `tiktoken` 模型提供本地缓存。这是通过在应用程序启动**之前**设置 `TIKTOKEN_CACHE_DIR` 环境变量来实现的。

当设置此环境变量时，`tiktoken` 将在指定的本地目录中查找其模型文件，而不是尝试从互联网下载它们。

### 实施解决方案的步骤：

1.  **创建模型缓存：** 在*有*互联网访问的环境中，运行提供的脚本以下载并缓存必要的 `tiktoken` 模型。

    ```bash
    # 运行缓存创建脚本
    uv run scripts/create_tiktoken_cache.py
    ```

    这将在项目根目录中创建一个 `tiktoken_cache` 目录，其中包含所需的模型文件。

2.  **配置环境变量：** 将以下行添加到您的 `.env` 文件中：

    ```bash
    TIKTOKEN_CACHE_DIR=./tiktoken_cache
    ```

    **重要：** 您应该确保 `.env` 文件在 `LightRAG` 导入 `tiktoken` **之前**加载，使此配置生效。

    ```python
    import os
    from typing import Dict, Any, Optional, Callable
    import sys
    import asyncio
    import atexit
    from dataclasses import dataclass, field
    from pathlib import Path
    from dotenv import load_dotenv

    # 将项目根目录添加到 Python 路径
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # 首先加载环境变量 - 在任何使用 tiktoken 的导入之前
    load_dotenv(dotenv_path=".env", override=False)

    # 现在导入 LightRAG（它将使用正确的环境变量集导入 tiktoken）
    from lightrag import LightRAG
    from lightrag.utils import logger

    # 其余代码...
    ```

### 测试离线设置

1.  **创建 `tiktoken_cache` 目录：** 如果您还没有，请在项目根目录中创建一个名为 `tiktoken_cache` 的目录。
2.  **填充缓存：** 运行 `scripts/create_tiktoken_cache.py` 脚本，将必要的 tiktoken 模型下载到 `tiktoken_cache` 目录中。
3.  **设置 `TIKTOKEN_CACHE_DIR` 环境变量：** 将 `TIKTOKEN_CACHE_DIR=./tiktoken_cache` 这行添加到您的 `.env` 文件中。
4.  **断开互联网连接：** 禁用您的互联网连接或将您的机器置于飞行模式。
5.  **运行应用程序：** 启动 `RAG-Anything` 应用程序。例如：
    ```
    uv run examples/raganything_example.py requirements.txt
    ```

通过遵循这些步骤，您可以消除网络依赖性，并在完全离线的环境中成功运行 `RAG-Anything` 项目。
