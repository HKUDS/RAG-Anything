## ADDED Requirements

### Requirement: Stats API returns accurate chunk count
The `/knowledge/stats` endpoint SHALL aggregate chunk counts from `kv_store_doc_status.json` instead of using `len(vdb_chunks.json)`.

#### Scenario: Chunk count accuracy
- **WHEN** a knowledge base has N documents each with their own `chunks_count`
- **THEN** `stats.chunks` equals the sum of all documents' `chunks_count`

#### Scenario: Missing doc_status file
- **WHEN** `kv_store_doc_status.json` does not exist
- **THEN** `stats.chunks` defaults to 0

### Requirement: Graph API returns complete data
The `/knowledge/graph` endpoint SHALL return all valid entities and relations without hardcoded truncation limits.

#### Scenario: Full entity retrieval
- **WHEN** a knowledge base has more than 40 entity names per entry
- **THEN** all valid entity names are included in the response nodes

#### Scenario: Full relation retrieval
- **WHEN** a knowledge base has more than 100 relation pairs per entry
- **THEN** all valid relation pairs are included in the response edges

#### Scenario: No artificial node/edge caps
- **WHEN** graph data exceeds 120 nodes or 80 edges
- **THEN** the response includes all nodes and edges without truncation
