# Running RAG-Anything in an Offline Environment

This document explains a critical consideration for running the RAG-Anything project in an environment with no internet access.

## The Network Dependency: `LightRAG` and `tiktoken`

The `RAGAnything` core engine relies on the `LightRAG` library for its primary functionality. `LightRAG`, in turn, uses OpenAI's `tiktoken` library for text tokenization.

By default, the `tiktoken` library has a network dependency. On its first use, it attempts to download tokenizer models from OpenAI's public servers (`openaipublic.blob.core.windows.net`). If the application is running in an offline or network-restricted environment, this download will fail, causing the `LightRAG` instance to fail to initialize.

This results in an error similar to the following:

```
Failed to initialize LightRAG instance: HTTPSConnectionPool(host='openaipublic.blob.core.windows.net', port=443): Max retries exceeded with url: /encodings/o200k_ba
```

This dependency is indirect. The `RAG-Anything` codebase itself does not directly import or call `tiktoken`. The call is made from within the `lightrag` library.

## The Solution: Using a Local `tiktoken` Cache

To resolve this issue and enable fully offline operation, you must provide a local cache for the `tiktoken` models. This is achieved by setting the `TIKTOKEN_CACHE_DIR` environment variable **before** the application starts.

When this environment variable is set, `tiktoken` will look for its model files in the specified local directory instead of attempting to download them from the internet.

### Steps to Implement the Solution:

1.  **Create a Model Cache:** In an environment *with* internet access, run the provided script to download and cache the necessary `tiktoken` models.

    ```bash
    # Run the cache creation script
    uv run scripts/create_tiktoken_cache.py
    ```

    This will create a `tiktoken_cache` directory in your project root containing the required model files.

2.  **Configure the Environment Variable:** Add the following line to your `.env` file:

    ```bash
    TIKTOKEN_CACHE_DIR=./tiktoken_cache
    ```

    **Important:** You should ensure that the `.env` file is loaded **before** `LightRAG` imports `tiktoken`, making this configuration effective.

    ```python
    import os
    from typing import Dict, Any, Optional, Callable
    import sys
    import asyncio
    import atexit
    from dataclasses import dataclass, field
    from pathlib import Path
    from dotenv import load_dotenv

    # Add project root directory to Python path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # Load environment variables FIRST - before any imports that use tiktoken
    load_dotenv(dotenv_path=".env", override=False)

    # Now import LightRAG (which will import tiktoken with the correct env var set)
    from lightrag import LightRAG
    from lightrag.utils import logger

    # Rest of the code...
    ```

### Testing the Offline Setup

1.  **Create a `tiktoken_cache` directory:** If you don't have one already, create a directory named `tiktoken_cache` in the project root.
2.  **Populate the cache:** Run the `scripts/create_tiktoken_cache.py` script to download the necessary tiktoken models into the `tiktoken_cache` directory.
3.  **Set the `TIKTOKEN_CACHE_DIR` environment variable:** Add the line `TIKTOKEN_CACHE_DIR=./tiktoken_cache` to your `.env` file.
4.  **Disconnect from the internet:** Disable your internet connection or put your machine in airplane mode.
5.  **Run the application:** Start the `RAG-Anything` application. For example:
    ```
    uv run examples/raganything_example.py requirements.txt
    ```

By following these steps, you can eliminate the network dependency and run the `RAG-Anything` project successfully in a fully offline environment.

## Containers

The images in `docker/` populate the tiktoken cache during the build and bake
in the MinerU weights, so a container built with the default arguments is
already offline-capable. See [docker.md](docker.md).
