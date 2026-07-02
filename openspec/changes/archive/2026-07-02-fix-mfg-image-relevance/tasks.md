## 1. Backend: Fix Image Relevance in QAEngine

- [x] 1.1 Rewrite `_match_relevant_images()` in `raganything/manufacturing/agent/qa_engine.py` with three-tier strategy (figure-number → caption-keyword → path-keyword)
- [x] 1.2 Add `_extract_figure_numbers()` helper to parse "图N"/"Figure N" patterns from text
- [x] 1.3 Add `_match_by_caption_keywords()` helper using jieba tokenizer intersection between image captions and query
- [x] 1.4 Add `_match_by_path_keywords()` helper using jieba tokenizer intersection between image file paths and query
- [x] 1.5 Remove `matched_fig_numbers = {1}` default fallback that returns first image unconditionally
- [x] 1.6 Ensure `_encode_image_data_url()` safety checks (file-exists, size < 2MB) are called before encoding
- [x] 1.7 Test: verify empty `related_images` when no figure number or keyword match exists

## 2. Backend: Enrich Parse Cache Image Loading

- [x] 2.1 Update `server.py:_get_mfg_agent_components()` image loading to preserve caption text alongside path+page
- [x] 2.2 Change `image_paths` list from `[(path, page)]` to `[(path, page, caption)]` tuples
- [x] 2.3 Update `QAEngine.__init__` to accept and store captions in image metadata
- [x] 2.4 Test: verify parse cache images include caption data when available

## 3. Frontend: Fix Quick Question Buttons

- [x] 3.1 Modify `handleQASend` in `ManufacturingAgentPage.jsx` to accept optional `presetQuery` parameter
- [x] 3.2 Remove `setTimeout(() => handleQASend(), 50)` hack from all preset question buttons
- [x] 3.3 Update preset question buttons to call `handleQASend(presetText)` directly
- [x] 3.4 Apply same fix to `startDiagnosis` in Fault Diagnosis tab
- [x] 3.5 Test: verify preset questions send immediately without race conditions

## 4. Frontend: Empty State with Onboarding Guidance

- [x] 4.1 Create `<EmptyState>` component with icon, title, description, and optional action buttons
- [x] 4.2 Add onboarding workflow card to `ManufacturingDashboardPage.jsx` (shown when all stats are zero)
- [x] 4.3 Add "import data → browse graph → start Q&A" three-step guidance with navigation buttons
- [x] 4.4 Conditionally hide onboarding card when dashboard data becomes available
- [x] 4.5 Test: verify onboarding card appears on fresh load and disappears after data import

## 5. Frontend: Agent Page Tab Guidance

- [x] 5.1 Enhance QA Tab empty state with descriptive hint text and 3 example question chips
- [x] 5.2 Add brief usage instructions to Code Parser Tab empty state
- [x] 5.3 Enhance Fault Diagnosis Tab empty state with description and 3 example fault description chips
- [x] 5.4 Test: verify all three tabs show appropriate guidance when empty

## 6. Integration Testing

- [ ] 6.1 Manual test: upload a manufacturing document, ask a question without figure references, verify no irrelevant images appear
- [ ] 6.2 Manual test: ask a question with "图X" reference, verify correct image is returned
- [ ] 6.3 Manual test: fresh deployment → Dashboard shows onboarding → import data → onboarding hides
- [ ] 6.4 Manual test: click preset question buttons, verify immediate send without setTimeout issues
