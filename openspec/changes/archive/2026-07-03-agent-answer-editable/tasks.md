## 1. Backend: Message ID Exposed + Update API

- [x] 1.1 Modify `pg_get_conversation()` to include `id` in SELECT and return `msg_id` per message
- [x] 1.2 Add `pg_update_message()` function with content validation and `edited_at` metadata
- [x] 1.3 Add `PUT /api/agents/{agent_id}/conversations/{thread_id}/messages/{message_id}` endpoint
- [x] 1.4 Add `MessageUpdateRequest` Pydantic model
- [x] 1.5 Add `GET /api/agents/{agent_id}/conversations/{thread_id}` endpoint for single conversation with messages

## 2. Frontend: API Layer

- [x] 2.1 Add `api.updateMessage()` function in api.js
- [x] 2.2 Add `api.getConversation()` function in api.js
- [x] 2.3 Fix `fetchJson`/`request` error handling for FastAPI 422 array-format detail

## 3. Frontend: Inline Edit UI

- [x] 3.1 Add edit state: `editingMsgId`, `editContent`
- [x] 3.2 Add handlers: `startEdit()`, `cancelEdit()`, `saveEdit()`
- [x] 3.3 Add edit button (Edit3 icon, hover-reveal) on completed assistant messages
- [x] 3.4 Add conditional textarea + save/cancel buttons when editing
- [x] 3.5 Add keyboard shortcuts: Ctrl+Enter save, Esc cancel
- [x] 3.6 Add "已编辑" indicator after successful edit
- [x] 3.7 Guard: only show edit button when `msg.msg_id != null`
- [x] 3.8 Update `loadThread` to use `getConversation` API (loads messages with msg_id)

## 4. Verification

- [x] 4.1 Backend: `pg_update_message()` unit test passed
- [x] 4.2 Backend: HTTP API endpoint test passed
- [x] 4.3 Frontend: `vite build` passes with zero errors
