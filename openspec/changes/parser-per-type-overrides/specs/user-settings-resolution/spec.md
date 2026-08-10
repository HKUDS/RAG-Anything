## ADDED Requirements

### Requirement: Ingestion schema supports per-file-type parser overrides
The `ingestion` section schema SHALL permit a `parsers_by_type` object whose keys are limited to `pdf`, `office`, and `image` and whose values are either the empty string (follow the global parser) or a supported parser id that supports that file type. Unknown keys, unsupported combinations (for example `opendataloader` for `office` or `image`, or `docling` for `image`), and non-string values (null or numbers) SHALL be rejected at save time. Values outside a non-empty platform `allowed.parsers` allow-list SHALL also be rejected. Empty-string values SHALL be removed before persistence so stored rows never contain them. Missing `parsers_by_type` in stored rows SHALL resolve to `{}` through default merging without a database migration.

#### Scenario: Save rejects OpenDataLoader for office
- **WHEN** a user submits `parsers_by_type.office = "opendataloader"`
- **THEN** the PATCH is rejected with a validation error and the stored settings are unchanged

#### Scenario: Save rejects Docling for image
- **WHEN** a user submits `parsers_by_type.image = "docling"`
- **THEN** the PATCH is rejected with a validation error

#### Scenario: Save rejects unknown type keys and non-string values
- **WHEN** a user submits a `parsers_by_type` key other than `pdf`, `office`, or `image`, or a value that is null or numeric
- **THEN** the PATCH is rejected with a validation error

#### Scenario: Platform allow-list restricts per-type overrides
- **WHEN** the platform `allowed.parsers` is a non-empty list and a user submits a per-type value outside it
- **THEN** the PATCH is rejected, while an empty allow-list permits any supported parser

#### Scenario: Empty-string overrides are normalized away
- **WHEN** a user saves `parsers_by_type` containing an empty-string value
- **THEN** the stored and effective `parsers_by_type` omit that key

#### Scenario: Existing rows resolve an empty per-type map
- **WHEN** a stored settings row has no `parsers_by_type`
- **THEN** the effective settings contain `parsers_by_type: {}` and global parser behavior is unchanged

### Requirement: Options catalog carries per-parser supported types
`GET /api/users/me/settings/options` SHALL include `supported_types` on each `parsers` catalog entry and SHALL keep applying the platform `allowed.parsers` allow-list to the catalog (non-empty restricts the list, empty returns the full catalog). Non-ingestion users SHALL continue to receive no parser catalog.

#### Scenario: Options include supported types for every parser
- **WHEN** a user with ingestion permission requests settings options
- **THEN** every `parsers` entry includes a `supported_types` array and `opendataloader` lists only `pdf`