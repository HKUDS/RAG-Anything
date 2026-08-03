## ADDED Requirements

### Requirement: Frontend code parsing uses the active autorepair route
Shipped frontend code SHALL use `/api/autorepair/code/parse` for G-code and PLC
parsing and SHALL NOT reference `/api/manufacturing/code/parse`.

#### Scenario: Code parsing request
- **WHEN** an authorized user submits G-code or PLC text in the editor
- **THEN** the client sends the existing parse payload to `/api/autorepair/code/parse`
