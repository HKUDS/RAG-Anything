## Why

Agent and autorepair question-and-answer pages duplicate authenticated POST,
response-error, and Server-Sent Events parsing. The copies have different
terminal-event behavior, so future fixes can drift between equivalent flows.

## What Changes

- Add a shared authenticated JSON/SSE streaming client beside the existing API
  helpers.
- Migrate the agent and autorepair streaming Q&A flows to that client.
- Preserve existing endpoints, event payloads, cancellation behavior, and page
  presentation while making `done`, `error`, malformed events, EOF, and abort
  handling consistent.

## Capabilities

### New Capabilities

- `frontend-streaming-client`: authenticated SSE request, event decoding, and
  terminal-state handling shared by shipped streaming pages.

### Modified Capabilities

None.

## Impact

`frontend/src/utils/api.js`, `AgentChatPage.jsx`, `AutoRepairAgentPage.jsx`,
and focused Node unit tests change. No backend route, response schema,
authorization policy, or dependency changes.
