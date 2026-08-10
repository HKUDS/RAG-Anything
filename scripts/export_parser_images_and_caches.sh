#!/usr/bin/env bash
# Build the parser-capable images and export them with model caches for an
# air-gapped or replacement Docker host. Database and user data are excluded.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
bundle_dir="${PARSER_BUNDLE_DIR:-$project_dir/deploy-artifacts/parser-runtime-$timestamp}"
app_image="${RAGANYTHING_APP_IMAGE:-raganything-app:parsers}"
marker_image="${RAGANYTHING_MARKER_IMAGE:-raganything-marker:parsers}"
nginx_image="${RAGANYTHING_NGINX_IMAGE:-raganything-nginx:parsers}"

if [[ "${1:-}" != "--skip-build" && -n "${1:-}" ]]; then
    echo "Usage: bash scripts/export_parser_images_and_caches.sh [--skip-build]" >&2
    exit 2
fi

mkdir -p "$bundle_dir"
if [[ "${1:-}" != "--skip-build" ]]; then
    docker compose build app marker nginx
fi

docker image inspect "$app_image" "$marker_image" "$nginx_image" >/dev/null
image_archive="$bundle_dir/raganything-parser-images.tar"
docker image save --output "$image_archive" "$app_image" "$marker_image" "$nginx_image"

cache_specs=(
    "huggingface|${HF_HOME_HOST_PATH:-./models/huggingface}"
    "paddle|${PADDLE_HOME_HOST_PATH:-./models/paddle}"
    "paddlex|${PADDLEX_HOME_HOST_PATH:-./models/paddlex}"
    "marker|${MARKER_CACHE_HOST_PATH:-./models/marker}"
)
cache_stage="$(mktemp -d)"
trap 'rm -rf "$cache_stage"' EXIT
mkdir -p "$cache_stage/models"
cache_count=0
for cache_spec in "${cache_specs[@]}"; do
    cache_name="${cache_spec%%|*}"
    cache_path="${cache_spec#*|}"
    if [[ -d "$cache_path" ]]; then
        ln -s "$(cd "$cache_path" && pwd)" "$cache_stage/models/$cache_name"
        ((cache_count += 1))
    else
        echo "Cache directory not present, skipped: $cache_path" >&2
    fi
done

if (( cache_count > 0 )); then
    tar -C "$cache_stage" -chzf "$bundle_dir/raganything-parser-model-caches.tar.gz" models
fi

sha256sum "$bundle_dir"/* > "$bundle_dir/SHA256SUMS"
printf 'Created parser runtime bundle: %s\n' "$bundle_dir"
