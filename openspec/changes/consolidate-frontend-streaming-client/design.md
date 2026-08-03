## Context

`api.js` already owns token lookup, auth-expiry handling, JSON decoding, and
HTTP error construction. Agent and autorepair pages each bypass those helpers
to implement an authenticated `fetch` plus newline-delimited SSE reader.

## Goals / Non-Goals

**Goals:**
- One helper owns authenticated streaming fetches, JSON error messages, UTF-8
  event framing, terminal events, and reader release.
- Both shipped Q&A pages retain their page-specific rendering through event
  callbacks.

**Non-Goals:**
- No EventSource migration, backend event/schema change, retry policy, or
  conversion of unrelated JSON and media requests.

## Decisions

- Export `streamSSE(url, { method, body, headers, signal, onEvent,
  onParseError })` from `api.js`. It accepts an existing absolute API path
  (such as `/api/agents/...`) without prefixing it, forwards all request
  options, resolves after a terminal callback, and rejects for HTTP failures,
  bodyless responses, EOF before terminal state, or abort.
- Treat `done` and `error` as terminal, cancel the reader, and release its
  lock immediately; normal EOF before either terminal event raises a stable
  connection error.
- Release the reader lock in unconditional cleanup for terminal, abort, and
  reader-error paths. The shared error decoder preserves string/object
  `detail`, top-level `message`, and plain-text bodies.
- Parse failures are supplied to an optional callback and do not discard later
  valid events from the same stream. The internal backend contract is one JSON
  payload per `data:` line; the decoder accepts LF/CRLF and chunk splits.

## Risks / Trade-offs

- [Page callbacks mutate different state shapes] -> preserve callback ownership
  and share only transport behavior.
- [A server sends non-JSON or partial frames] -> buffer UTF-8 chunks to complete
  lines and surface malformed complete frames without ending the stream.
- [Cancellation races with terminal delivery] -> propagate `AbortError` and let
  existing page cleanup remain authoritative.
