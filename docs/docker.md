# Running RAG-Anything in a Container

The `docker/` directory contains images that bundle RAG-Anything with the
external programs it needs: MinerU and its models, LibreOffice for Office
documents, ffmpeg for audio and video, and the WeasyPrint libraries for the
markdown extra. This avoids installing any of that on the host.

Both images build from the repository root, so the image contains the working
tree rather than the published package.

## Quick start

```bash
cp env.example .env          # add your OPENAI_API_KEY
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml run --rm raganything check
```

`check` prints the resolved versions of Python, RAG-Anything, MinerU, torch,
LibreOffice and ffmpeg, and confirms the package imports.

To process a document:

```bash
docker compose -f docker/compose.yaml run --rm raganything \
    example /data/input/document.pdf --api-key "$OPENAI_API_KEY"
```

## CPU and GPU images

```bash
# CPU
docker build -f docker/Dockerfile -t raganything:cpu .

# CUDA
docker build -f docker/Dockerfile.gpu -t raganything:gpu .
docker run --rm -it --gpus all --env-file .env -v raganything-data:/data raganything:gpu
```

The CPU image installs torch from the PyTorch CPU index. Letting pip resolve
torch from PyPI on a CPU-only image pulls the CUDA build and roughly 3 GB of
`nvidia-*` wheels that are never loaded.

## Build arguments

| Argument | Default | Purpose |
| --- | --- | --- |
| `EXTRAS` | `all` | extras to install, or `none` for the core package |
| `BAKE_MODELS` | `1` | download MinerU pipeline weights during the build |
| `WITH_OFFICE` | `1` | install LibreOffice for `.doc`, `.ppt` and `.xls` files |
| `WITH_MEDIA` | `1` | install ffmpeg for the audio and video extras |
| `WITH_CJK` | `0` | install Noto CJK fonts |
| `PUID`, `PGID` | `10001` | uid and gid of the runtime user |

With `BAKE_MODELS=0` the image is far smaller but the first parse downloads
the weights. Set `MINERU_MODEL_SOURCE=huggingface` at runtime in that case,
and mount a volume at `/opt/models` so the download is only paid once.

## Volumes and persistent data

Everything that must outlive the container lives under `/data`.

| Path | Variable | Contents |
| --- | --- | --- |
| `/data/input` | | source documents |
| `/data/output` | `OUTPUT_DIR` | MinerU artefacts: markdown, JSON, page images |
| `/data/rag_storage` | `WORKING_DIR` | LightRAG knowledge graph, vectors, caches |

`rag_storage` is the one that matters. Losing `output` costs a re-parse;
losing `rag_storage` costs a full re-index and the model spend that goes with
it. With the default file backend it holds a GraphML entity graph, three
vector stores, and key-value stores for documents, chunks, document status
and the LLM response cache.

Model weights live at `/opt/models` and are deliberately not a declared
volume. Mounting over that path hides the baked models and forces a download.

### Choosing a storage backend

The default file storage has no locking and is only safe for a single
container. For concurrent use, point LightRAG at PostgreSQL, Neo4j, MongoDB,
Redis, Milvus or Qdrant through the usual `LIGHTRAG_*_STORAGE` variables in
`.env`. The `/data/rag_storage` volume then stops being the source of truth.

### Bind mounts on Linux

The container runs as uid 10001. A bind-mounted host directory owned by a
different uid will not be writable, and the first insert will fail. Either
keep the named volume, or build with your own ids:

```bash
docker build -f docker/Dockerfile \
    --build-arg PUID=$(id -u) --build-arg PGID=$(id -g) \
    -t raganything:cpu .
```

## Offline use

Both images are self-contained when built with the defaults. The MinerU
weights are baked in, and `scripts/create_tiktoken_cache.py` runs during the
build so the tokenizer never reaches for the network. See
[offline_setup.md](offline_setup.md) for the background on that dependency.

This can be confirmed with networking disabled:

```bash
docker run --rm --network none -v raganything-data:/data raganything:cpu \
    mineru -p /data/input/document.pdf -o /data/output -b pipeline -d cpu
```
