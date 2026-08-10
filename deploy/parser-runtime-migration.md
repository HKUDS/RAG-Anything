# Parser Runtime Migration

The Compose deployment uses three images:

- `raganything-app:parsers`: application, PaddleOCR, PaddlePaddle,
  OpenDataLoader, Java 17, and the normal document parsers.
- `raganything-marker:parsers`: Marker in a separate Python environment.
  This separation is required because Marker requires `Pillow<11`, while the
  main MinerU runtime requires a newer Pillow.
- `raganything-nginx:parsers`: frontend reverse proxy.

The images do not contain PostgreSQL data, uploads, RAG storage, or downloaded
model files. Those are host-mounted paths or Docker volumes and must be backed
up separately before moving to a new server.

## Export From The Current Server

Run this from `/opt/rag-anything` after the parser images have been tested:

```bash
bash scripts/export_parser_images_and_caches.sh
```

It builds `app`, `marker`, and `nginx`, then writes a timestamped directory
under `deploy-artifacts/` containing:

- `raganything-parser-images.tar`
- `raganything-parser-model-caches.tar.gz` when any cache exists
- `SHA256SUMS`

The cache archive contains the mounted Hugging Face, PaddleOCR, PaddleX, and
Marker/Surya/Torch cache directories. It contains no `.env` file or database.
Copy the bundle, the reviewed Compose source, and a separately protected copy
of `.env` to the replacement server. Validate the checksums before importing.

```bash
sha256sum -c SHA256SUMS
docker image load --input raganything-parser-images.tar
tar -xzf raganything-parser-model-caches.tar.gz -C /opt/rag-anything
```

The new server still needs Docker Engine and the Compose plugin. It does not
need to reinstall these parser Python packages when the exported images are
loaded successfully.

## Data Backup

Before replacing a production host, take a PostgreSQL logical backup and copy
the bind-mounted user data. Do not copy Docker's PostgreSQL volume while the
database is running.

```bash
mkdir -p backups
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" \
  --format=custom > backups/raganything-postgres.dump
tar -czf backups/raganything-user-data.tar.gz rag_storage uploads output
```

Restore the database before starting the application on the new server, then
start it without rebuilding images:

```bash
docker compose up -d --no-build
```

## Persistent Cache Paths

`docker-compose.yml` mounts these host paths by default. Override their names
with the corresponding `.env` variables when storage lives outside the source
checkout.

| Host path | Environment variable | Contents |
| --- | --- | --- |
| `./models/huggingface` | `HF_HOME_HOST_PATH` | Docling and main-app Hugging Face models |
| `./models/paddle` | `PADDLE_HOME_HOST_PATH` | PaddleOCR model cache |
| `./models/paddlex` | `PADDLEX_HOME_HOST_PATH` | PaddleX model cache used by newer PaddleOCR releases |
| `./models/marker` | `MARKER_CACHE_HOST_PATH` | Marker, Surya, Torch, and Marker Hugging Face models |

For restricted networks, retain `HF_ENDPOINT=https://hf-mirror.com` in the
server `.env`. The Hugging Face cache is mounted at the same path as
`HF_HOME` and `HF_HUB_CACHE`, so model files downloaded through the mirror
survive a container recreation.

## Post-Restore Verification

Wait for the services to become healthy, then verify the application-side
catalog. All three parser ids must report `True`.

```bash
docker compose ps
docker compose exec app python -c "from raganything.parser import get_parser; [print(name, get_parser(name).check_installation()) for name in ('paddleocr', 'marker', 'opendataloader')]"
```

The first real parse can download any previously uncached parser model into its
mounted cache. Keep the Marker service internal to Compose; it intentionally
has no host `ports` entry.
