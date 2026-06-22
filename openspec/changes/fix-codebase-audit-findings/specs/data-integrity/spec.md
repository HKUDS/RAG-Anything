# Data Integrity

## ADDED Requirements

### Requirement: KB metadata is written atomically
The `save_kb_meta()` function SHALL write to a `.tmp` file and atomically replace the target file using `Path.replace()`.

#### Scenario: Crash during KB metadata write
- **WHEN** the server crashes while `save_kb_meta()` is executing
- **THEN** the `rag_storage_kb_meta.json` file remains intact (either the old version or the complete new version, never truncated)

#### Scenario: Normal KB metadata save
- **WHEN** `save_kb_meta()` is called with updated metadata
- **THEN** `rag_storage_kb_meta.json` contains the updated data

### Requirement: Query history is written atomically with debounce
The `save_query_history()` function SHALL use atomic write pattern and debounce writes to at most once per 5 seconds.

#### Scenario: Rapid consecutive queries
- **WHEN** 10 queries complete within 1 second
- **THEN** `query_history.json` is written at most once (after the last query), not 10 times

#### Scenario: Crash during query history write
- **WHEN** the server crashes during a debounced `save_query_history()` write
- **THEN** the `query_history.json` file is not corrupted

### Requirement: KB initialization is serialized per KB name
The `get_kb()` function SHALL use an `asyncio.Lock` keyed by KB name to prevent concurrent initialization of the same knowledge base.

#### Scenario: Concurrent requests for the same uninitialized KB
- **WHEN** two concurrent requests call `get_kb("my_kb")` and `my_kb` is not yet initialized
- **THEN** exactly one `RAGAnything` instance is created, and both requests receive the same instance

#### Scenario: Requests for different KBs proceed concurrently
- **WHEN** two concurrent requests call `get_kb("kb_a")` and `get_kb("kb_b")`
- **THEN** both initializations proceed independently without blocking each other

### Requirement: is_admin column is no longer written on user creation
The `create_user()` function SHALL NOT include `is_admin` in the INSERT statement. Admin status SHALL only be determined by the `role_id` foreign key.

#### Scenario: New user created with admin role
- **WHEN** a user is created with `role_id=1` (admin role)
- **THEN** the `users` table row has `role_id=1` and `is_admin` is not explicitly set (defaults to 0, but is never read for auth decisions)

#### Scenario: Login response derives admin status from role
- **WHEN** a user logs in successfully
- **THEN** the response `is_admin` field is derived from `role_id` via the roles table, not from the `is_admin` column

### Requirement: users.role_id has a database index
The `users` table SHALL have an index on `role_id` for efficient JOIN queries.

#### Scenario: get_user_role query
- **WHEN** `get_user_role(user_id)` is called
- **THEN** the SQLite query uses the `idx_users_role_id` index for the JOIN

### Requirement: init_db() migration errors are narrowly caught
Column migration in `init_db()` SHALL only catch `sqlite3.OperationalError` with "duplicate column" message, re-raising all other errors.

#### Scenario: Duplicate column migration (idempotent)
- **WHEN** `init_db()` runs a migration that has already been applied
- **THEN** the "duplicate column name" error is silently caught and execution continues

#### Scenario: Disk-full error during migration
- **WHEN** `init_db()` migration fails due to disk space exhaustion
- **THEN** the error is re-raised (not silently swallowed)

## MODIFIED Requirements

### Requirement: save_kb_meta preserves data integrity on write failure
The system SHALL NOT leave `rag_storage_kb_meta.json` in a truncated state if the write operation fails partway through.

#### Scenario: Disk full during save
- **WHEN** `save_kb_meta()` is called and the disk is full
- **THEN** the original file remains unchanged (tmp write fails, replace never occurs)
