# Multimodal RAG: common failure modes and quick checks

Real-world PDFs and Office files are noisy. RAG-Anything (MinerU / Docling / etc.) usually does the right thing, but when something feels “off”, this page is a **short sanity checklist** before opening an issue.

It is meant to stay small and easy to maintain (see discussion in [#207](https://github.com/HKUDS/RAG-Anything/issues/207) and [#213](https://github.com/HKUDS/RAG-Anything/issues/213)).

---

## 1. OCR or layout silently corrupts text

**Symptoms:** answers quote nonsense, wrong numbers, or mixed columns.

**Quick checks:**

- Open the parser’s Markdown or `*_content_list.json` for the same page and eyeball a few paragraphs.
- Compare with the source PDF zoomed in (sometimes OCR confuses `l`/`1`, ligatures, or watermarks).

---

## 2. Table structure lost during preprocessing

**Symptoms:** merged cells, tables shown as plain lines, or wrong row order.

**Quick checks:**

- Find the `type: table` blocks in `content_list` and see if `table_body` / structure fields look plausible.
- If you only need retrieval, sometimes a **flattened** table is acceptable; if you need exact structure, try another parse method or parser (`PARSE_METHOD`, `PARSER` in `.env`).

---

## 3. Image ↔ caption misalignment

**Symptoms:** captions match the wrong figure, or images appear in the wrong order.

**Quick checks:**

- Confirm `img_path` / captions exist in `content_list` and that page indices look consistent.
- For DOCX pipelines, remember that exporting to PDF for OCR can **drop inline math**; OMML helpers in recent versions exist specifically to recover equations from the original Word file.

---

## 4. Retrieval biased toward text (image/table ignored)

**Symptoms:** the answer clearly needs a figure or table, but only text chunks rank high.

**Quick checks:**

- Run a **probe question** that can only be answered from an image or table (not from surrounding text).
- Inspect whether multimodal stages ran (`ENABLE_*_PROCESSING` flags) and whether your embedding path actually sees the enriched text (not only raw OCR).

---

## 5. “Everything’s slow” vs “stuck”

**Symptoms:** long runs, high CPU/GPU.

**Quick checks:**

- [#48](https://github.com/HKUDS/RAG-Anything/issues/48) style: large PDFs and OCR are inherently heavy—batch size and hardware matter.
- Distinguish **slow but progressing** from a **hang** (then check subprocess timeouts, MinerU/Docling logs, and disk space).

---

## 6. Images not loading in your UI after indexing

**Symptoms:** chunks reference paths that only exist on the machine that ingested the data.

**Quick checks:**

- Absolute local paths are normal for processing on one host. For a browser or another server, set **public URL mapping** (environment variables `RAGANYTHING_PUBLIC_ASSET_BASE_URL` and `RAGANYTHING_PUBLIC_ASSET_STRIP_PREFIX` — see the main [README](../README.md)) so each chunk can carry an `*_public_url` field alongside the local path. Today this mapping only runs in the MinerU parser path; other parsers will not yet produce `*_public_url`.

---

## When you open an issue

Including the items below speeds up triage:

- Which **modality** failed (text / image / table / equation).
- Which **parser** and **`PARSE_METHOD`** you used.
- A **minimal** file (or a redacted excerpt) and one **query** that misbehaves.

---

*This document is intentionally short. If you expand it, prefer adding links to reproducible examples rather than long narratives.*
