#!/usr/bin/env python3
"""Synthetic bench: compare multimodal KG extraction modes by mock LLM call count.

Does not call a real LLM. Useful for verifying issue #348 mitigations locally:

    python examples/multimodal_ingest_call_count_bench.py

Reports approximate vision + extract invocations for N image blocks under
``packed``, ``per_item``, and ``skip`` modes (merge LLM calls are not simulated).
"""

from __future__ import annotations

class FakeTokenizer:
    def encode(self, text: str):
        return list(range(max(1, len(text) // 4)))


def _estimate(mode: str, n_images: int, caption_chars: int = 400, budget: int = 1200):
    """Estimate calls without importing the full processor stack."""
    vision = n_images
    caption_tokens = max(1, caption_chars // 4)
    if mode == "skip":
        extract = 0
    elif mode == "per_item":
        extract = n_images
    else:  # packed
        total = n_images * caption_tokens
        extract = max(1, (total + budget - 1) // budget) if n_images else 0
    return {"vision": vision, "extract_chunks": extract, "approx_llm_min": vision + extract}


def main():
    n = 8
    print(f"Synthetic page with {n} image blocks (caption ~400 chars each)\n")
    print(f"{'mode':<10} {'vision':>8} {'extract':>8} {'min_llm':>8}")
    print("-" * 40)
    for mode in ("per_item", "packed", "skip"):
        stats = _estimate(mode, n)
        print(
            f"{mode:<10} {stats['vision']:>8} {stats['extract_chunks']:>8} "
            f"{stats['approx_llm_min']:>8}"
        )
    print(
        "\nNotes:\n"
        "- per_item ≈ legacy behaviour (1 extract / image) before #348 fix.\n"
        "- packed (default) packs description-only captions into chunk_token_size units.\n"
        "- skip stores vision results without multimodal extract/merge.\n"
        "- Real merge summarization can add more LLM calls when entities collide;\n"
        "  omitting neighbor_text from extraction (packed/per_item) reduces that.\n"
        "- Configure via MULTIMODAL_KG_EXTRACTION_MODE / RAGAnythingConfig.\n"
    )


if __name__ == "__main__":
    main()
