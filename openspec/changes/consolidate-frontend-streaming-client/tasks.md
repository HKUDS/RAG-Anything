## 1. Shared transport

- [x] 1.1 Add authenticated SSE request, error decoding, event framing, and terminal handling to the API utility.
- [x] 1.2 Add focused transport tests for headers, JSON/text HTTP errors and 401 auth expiry, done/error cancellation, EOF/bodyless responses, malformed CRLF/UTF-8 frames including final data lines, and abort/reader cleanup.

## 2. Migrate callers

- [x] 2.1 Migrate AgentChatPage to the shared streaming utility without changing its event presentation.
- [x] 2.2 Migrate AutoRepairAgentPage to the shared streaming utility without changing its event presentation.
- [x] 2.3 Add caller-boundary regression coverage for terminal/cancellation behavior, URLs, payload forwarding, and each page's event rendering contract.

## 3. Verification and documentation

- [ ] 3.1 Run frontend unit tests and production build.
- [x] 3.2 Update PROJECT_SUMMARY.md with the completed behavior and validation result.
