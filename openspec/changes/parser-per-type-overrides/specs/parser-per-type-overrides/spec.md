## ADDED Requirements

### Requirement: Per-file-type parser overrides dispatch by extension
The document processor SHALL resolve the effective parser per file by mapping the file extension to a type (`pdf`, `office`, `image`, `video`, or generic) and applying precedence: an explicit user override for that type wins, then the deployment `PDF_PARSER` environment override applies only to `pdf`, and the global parser is the final default. `office` SHALL cover doc/docx/ppt/pptx/xls/xlsx/html/htm/xhtml; `image` SHALL cover image extensions; `video` SHALL bypass parser instantiation entirely under every parser configuration; other formats SHALL use the global parser. The OpenDataLoader guard SHALL reject the parser only for non-`pdf` types and SHALL remain active as defense in depth.

#### Scenario: User overrides PDF parser
- **WHEN** a user sets `parsers_by_type.pdf` to a parser while the global parser is different
- **THEN** PDF uploads use the per-type parser and office/image uploads keep using the global parser

#### Scenario: Deployment PDF override applies without user override
- **WHEN** `PDF_PARSER` is set and no user override exists for `pdf`
- **THEN** PDF uploads use the deployment override while other types use the global parser

#### Scenario: Video never instantiates a parser even with OpenDataLoader as global parser
- **WHEN** a video file is processed while the global parser is `opendataloader`
- **THEN** the video is routed to the multimodal video processor without instantiating or rejecting via any document parser

#### Scenario: Docling parses HTML through its HTML pipeline
- **WHEN** a user uploads an `.html`/`.htm`/`.xhtml` file with `docling` as the effective parser
- **THEN** the document is parsed through the docling HTML pipeline instead of being rejected as an unsupported office format

### Requirement: Parser catalog declares supported file types
The personal settings options response SHALL include, for every parser catalog entry, a `supported_types` array listing the file types that parser genuinely supports (`docling → ["pdf","office"]`; `mineru`/`marker`/`paddleocr → ["pdf","office","image"]`; `opendataloader → ["pdf"]`). The frontend SHALL only offer parsers whose `supported_types` includes the selected file type, SHALL put a “follow default” choice first, and SHALL disable uninstalled parsers.

#### Scenario: Frontend offers only supported parsers per type
- **WHEN** a user opens the per-type parser dropdown for office documents
- **THEN** `opendataloader` is not offered while `docling`, `mineru`, `marker`, and `paddleocr` are offered

#### Scenario: Uninstalled parser is disabled
- **WHEN** a parser reports `available=false` and supports the current file type
- **THEN** the option appears grayed out and cannot be selected