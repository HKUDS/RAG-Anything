## ADDED Requirements

### Requirement: Download button in document table action column
The system SHALL display a download button in the document list table's action column for every document that has an original file. Clicking the button SHALL trigger a native browser download of the original uploaded file.

#### Scenario: Download button shown for file-uploaded document
- **WHEN** a document was created via file upload and has a valid `file` field (not `"?"`)
- **THEN** the action column in the document table SHALL render a download button (`Download` icon from lucide-react)

#### Scenario: Download button hidden for content-pasted document
- **WHEN** a document was created via paste content or URL import (indicated by `file === "?"` or empty `file_path` in DB)
- **THEN** the action column SHALL NOT render a download button for that document

#### Scenario: Download button triggers browser native download
- **WHEN** the user clicks the download button
- **THEN** the browser SHALL initiate a native download using an `<a>` tag pointing to the download endpoint with auth token in query parameter

### Requirement: Clickable filename for download
The document filename in the list table SHALL be rendered as a clickable link that triggers a native browser download of the original file.

#### Scenario: Filename is a clickable download link
- **WHEN** a document has a valid original file
- **THEN** the filename cell SHALL render as an `<a>` tag with `href` pointing to the download endpoint with auth token

#### Scenario: Filename is plain text for file-less document
- **WHEN** a document has no original file (`file === "?"`)
- **THEN** the filename SHALL be rendered as plain text (non-clickable)

### Requirement: Download button in document detail panel
The system SHALL display a download button at the bottom of the document detail slide-out panel for documents that have an original file.

#### Scenario: Download button in detail panel
- **WHEN** the user opens the document detail panel for a document with an original file
- **THEN** the panel SHALL render a download button below the metadata fields

#### Scenario: Download button hidden in detail panel for file-less document
- **WHEN** the user opens the document detail panel for a document without an original file
- **THEN** the panel SHALL NOT render a download button

### Requirement: Token-based authentication for download endpoint
The download endpoint SHALL support authentication via `?token=xxx` query parameter as a fallback to the `Authorization` header, enabling `<a>` tag-based downloads.

#### Scenario: Download with query parameter token
- **WHEN** a GET request is made to `/api/knowledge/documents/{doc_id}/download?kb=xxx&token=yyy` with a valid token
- **THEN** the server SHALL authenticate the user and return the file

#### Scenario: Download with Authorization header (backward compatible)
- **WHEN** a GET request is made with a valid `Authorization: Bearer xxx` header but no `?token` parameter
- **THEN** the server SHALL authenticate via the header as before

#### Scenario: Download without any authentication
- **WHEN** a GET request is made without any valid token (neither query param nor header)
- **THEN** the server SHALL return HTTP 401 Unauthorized

### Requirement: Frontend API helper constructs download URL with token
The `downloadDocumentUrl` helper in the frontend API module SHALL append the current user's auth token to the generated URL.

#### Scenario: URL includes token parameter
- **WHEN** `downloadDocumentUrl(docId)` is called while a user is authenticated
- **THEN** the returned URL SHALL contain `?kb=<currentKB>&token=<userToken>`
