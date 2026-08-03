## ADDED Requirements

### Requirement: Shared authenticated SSE transport
Shipped frontend streaming requests SHALL use one API utility that attaches the
current bearer token, applies the existing authentication-expiry behavior, and
converts unsuccessful HTTP responses into a user-safe error.

#### Scenario: Authorized streaming request
- **WHEN** an authenticated user starts an agent or autorepair Q&A stream
- **THEN** the client SHALL POST the existing request payload with its bearer token and preserve the endpoint-specific URL

#### Scenario: Unauthorized streaming request
- **WHEN** a streaming endpoint returns HTTP 401
- **THEN** the utility SHALL apply the existing auth-expiry behavior and reject the stream with an error

#### Scenario: Invalid streaming response
- **WHEN** a streaming endpoint returns a non-401 error or a successful response without a readable body
- **THEN** the utility SHALL reject with a user-safe decoded HTTP or unexpected-disconnect error

### Requirement: Shared SSE terminal handling
The shared frontend SSE utility SHALL decode JSON `data:` events and treat
`done` and `error` event types as terminal.

#### Scenario: Terminal event arrives
- **WHEN** a stream emits a `done` or `error` event
- **THEN** the utility SHALL invoke the page event callback, release the reader, and resolve without reading later chunks

#### Scenario: Stream ends without terminal event
- **WHEN** the response body reaches EOF before a `done` or `error` event
- **THEN** the utility SHALL reject with a user-safe unexpected-disconnect error

#### Scenario: Malformed event frame
- **WHEN** a complete SSE `data:` frame is not valid JSON
- **THEN** the utility SHALL report it through its parse-error callback and continue consuming later frames

#### Scenario: Chunked CRLF event frame
- **WHEN** a JSON `data:` event is split across response chunks using CRLF line endings
- **THEN** the utility SHALL decode it once and pass the reconstructed event to the page callback
