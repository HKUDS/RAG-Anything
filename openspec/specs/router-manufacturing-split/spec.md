## ADDED Requirements

### Requirement: Manufacturing routes in dedicated module

All `/api/manufacturing/*` routes SHALL be extracted from `raganything/routers/admin.py` into a new `raganything/routers/manufacturing.py` router module. Manufacturing helper functions (`_get_manufacturing`, `_get_mfg_agent_components`, `_get_mfg_qa_engine`) SHALL be defined in `manufacturing.py` rather than in `admin.py`.

#### Scenario: Manufacturing routes are accessible

- **WHEN** the server starts with the new `manufacturing_router` registered
- **THEN** all 12 manufacturing endpoints are served at their original paths:
  - `GET /api/manufacturing/knowledge-graph/summary`
  - `GET /api/manufacturing/knowledge-graph/nodes`
  - `GET /api/manufacturing/knowledge-graph/nodes/{node_id}`
  - `GET /api/manufacturing/knowledge-graph/nodes/{node_id}/lineage`
  - `GET /api/manufacturing/process-library/search`
  - `GET /api/manufacturing/process-library/categories`
  - `GET /api/manufacturing/fault-cases/search`
  - `GET /api/manufacturing/fault-cases/stats`
  - `POST /api/manufacturing/code/parse`
  - `GET /api/manufacturing/dashboard`
  - `GET /api/manufacturing/institutions`
  - `POST /api/manufacturing/qa`
  - `POST /api/manufacturing/qa/stream`
  - `POST /api/manufacturing/fault-diagnosis`
  - `POST /api/manufacturing/fault-diagnosis/continue`
  - `GET /api/manufacturing/kb-list`
  - `GET /api/manufacturing/health`

#### Scenario: admin.py below 400 lines

- **WHEN** counting lines in `raganything/routers/admin.py` after extraction
- **THEN** the line count is below 400 (down from 861)

#### Scenario: manufacturing.py below 400 lines

- **WHEN** counting lines in `raganything/routers/manufacturing.py`
- **THEN** the line count is below 400

#### Scenario: Existing tests pass without modification

- **WHEN** running `pytest tests/ -q`
- **THEN** the test count is >= 356 passed
- **THEN** no new test failures are introduced
