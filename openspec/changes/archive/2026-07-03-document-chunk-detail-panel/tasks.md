## 1. Backend: Chunk Detail API

- [x] 1.1 Add `GET /api/knowledge/documents/{doc_id}/chunks` endpoint in `raganything/routers/knowledge.py`
- [x] 1.2 Implement chunk retrieval: read `chunks_list` from `doc_status`, batch-fetch from `text_chunks` KV storage, sort by `chunk_order_index`
- [x] 1.3 Implement media path extraction: parse `Image Path:` / `Table Image Path:` from chunk content to populate `media_path` field
- [x] 1.4 Implement `media_url` calculation using `asset_urls.public_url_for_local_path()` when `RAGANYTHING_PUBLIC_ASSET_BASE_URL` env is configured
- [x] 1.5 Add defensive handling: skip chunk IDs not found in `text_chunks`, return 404 for unknown document
- [x] 1.6 Add `api.getDocumentChunks(docId)` function in `frontend/src/utils/api.js`

## 2. Frontend: Clickable Chunk Count

- [x] 2.1 Replace plain `{doc.chunks}` text at KnowledgeDetailPage.jsx with a styled button
- [x] 2.2 Add hover state (`hover:text-sky-600 hover:underline cursor-pointer`) and focus ring
- [x] 2.3 Add click handler that fetches chunk data and opens the detail panel

## 3. Frontend: Chunk Detail Drawer

- [x] 3.1 Add state: `chunkPanelDoc` (active document), `chunksData` (array), `chunksLoading` (loading flag)
- [x] 3.2 Build drawer shell: `fixed inset-0 z-50 flex justify-end` overlay + backdrop + slide-in panel with framer-motion
- [x] 3.3 Add header: document name + close button (X icon)
- [x] 3.4 Add statistics summary row: total chunks count, total tokens (sum of `tokens` field)
- [x] 3.5 Handle loading state with spinner (Loader2 icon) and error state with toast message
- [x] 3.6 Close on backdrop click, close button, and Escape keydown listener

## 4. Frontend: Chunk List with Expand/Collapse

- [x] 4.1 Render chunk list: each chunk as a collapsible row with `ChevronRight` icon rotating 90° on expand
- [x] 4.2 Collapsed state: show chunk index (#1, #2...), token count, page number, type badge, 120-char text preview with "…"
- [x] 4.3 Expanded state: show full content in scrollable text block with `font-mono` styling
- [x] 4.4 Initialize `expandedChunks` state with `{0: true}` (first chunk expanded by default)
- [x] 4.5 Add "全部展开" and "全部折叠" buttons
- [x] 4.6 Use `framer-motion` `AnimatePresence` for smooth expand/collapse animation

## 5. Frontend: Multimodal Chunk Display

- [x] 5.1 Add type badge: render type-specific icon (`ImageIcon`, `Table`, `Sigma`, `Video`) based on `original_type`
- [x] 5.2 Add thumbnail rendering: `media_url` > `/api/files/image` endpoint > no thumbnail
- [x] 5.3 Style thumbnail: 120px × 80px, object-cover, rounded, border
- [x] 5.4 Add image error handling: `onError` handler hides broken image
- [x] 5.5 Show `modal_entity_name` as label next to type badge

## 6. Frontend: Text Filter

- [x] 6.1 Add filter input at top of chunk list with `Search` icon
- [x] 6.2 Implement client-side filter: `content.toLowerCase().includes(filterText.toLowerCase())`
- [x] 6.3 Update display counter: "显示 3 / 15 块" when filter active
- [x] 6.4 Show empty state "没有匹配的切块" when filter matches zero chunks

## 7. Verification

- [ ] 7.1 Manual test: upload a small text file, verify chunk count is clickable and panel opens
- [ ] 7.2 Manual test: test expand/collapse of individual chunks and all-expand/all-collapse buttons
- [ ] 7.3 Manual test: test text filter with Chinese and English keywords
- [ ] 7.4 Manual test: upload a PDF with images, verify multimodal chunks show type icons and thumbnails
- [ ] 7.5 Manual test: verify panel closes via backdrop click, X button, and Escape key
- [ ] 7.6 Manual test: verify 404 handling for deleted documents
