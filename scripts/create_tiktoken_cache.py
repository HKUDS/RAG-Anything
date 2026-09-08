import tiktoken
import os

# Define the directory where you want to store the cache
cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR", "./tiktoken_cache")
os.environ["TIKTOKEN_CACHE_DIR"] = cache_dir

# Create the directory if it doesn't exist
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)

# LightRAG's default tokenizer resolves to o200k_base; cl100k_base is still
# used by older models and by callers that pass an explicit encoding name.
ENCODINGS = ("o200k_base", "cl100k_base")

print("Downloading and caching tiktoken models...")
for encoding in ENCODINGS:
    tiktoken.get_encoding(encoding)
    print(f"  cached {encoding}")

print(f"tiktoken models have been cached in '{cache_dir}'")
