# worker-file-lock Specification

## Purpose
TBD - created by archiving change prevent-duplicate-processes. Update Purpose after archive.
## Requirements
### Requirement: Worker acquires exclusive file lock before processing
Before a worker subprocess begins processing a file, it SHALL acquire an exclusive OS-level file lock on `<working_dir>/.locks/<file_hash>.lock`. If the lock cannot be acquired, the worker SHALL exit with a non-zero exit code.

#### Scenario: Lock acquired successfully
- **WHEN** a worker starts and no other worker holds the lock for the target file
- **THEN** the worker acquires the lock and proceeds with processing

#### Scenario: Lock acquisition fails
- **WHEN** a worker starts and another worker already holds the lock for the target file
- **THEN** the worker logs "File {file_path} is already being processed by another worker" and exits with code 3

#### Scenario: Lock released on worker exit
- **WHEN** a worker process exits (normally or abnormally)
- **THEN** the OS automatically releases the file lock

### Requirement: Worker validates doc_status before processing
Before acquiring the file lock, the worker SHALL check `doc_status` for the target document. If the document is already in "processing" status with a recent `updated_at` timestamp (within 5 minutes), the worker SHALL exit before attempting to acquire the lock.

#### Scenario: Document already processing recently
- **WHEN** a worker starts for a document that has `status == "processing"` and `updated_at` is less than 5 minutes ago
- **THEN** the worker exits with code 3 and logs "Document appears to have an active processor"

#### Scenario: Stale processing status
- **WHEN** a worker starts for a document that has `status == "processing"` but `updated_at` is more than 5 minutes ago
- **THEN** the worker treats the status as stale and proceeds with the file lock check

### Requirement: Cross-platform lock implementation
The file lock SHALL work on both Windows and Unix-like systems using only Python standard library modules.

#### Scenario: Lock on Windows
- **WHEN** a worker runs on Windows
- **THEN** it uses `msvcrt.locking` to acquire an exclusive file lock

#### Scenario: Lock on Unix
- **WHEN** a worker runs on Linux or macOS
- **THEN** it uses `fcntl.flock` to acquire an exclusive file lock

### Requirement: Lock directory isolation
Lock files SHALL be stored in a centralized `<working_dir>/.locks/` directory, separate from Knowledge Base storage directories.

#### Scenario: Lock directory auto-created
- **WHEN** the first lock is requested and `.locks/` directory does not exist
- **THEN** the directory is created with default permissions

#### Scenario: Multiple KBs share lock directory
- **WHEN** workers for different KBs acquire locks
- **THEN** all lock files reside in the same `.locks/` directory, distinguished by file hash

