## ADDED Requirements

### Requirement: Subprocess waits for background tasks before exit
The document processing subprocess (`process_worker.py`) SHALL wait for all pending background multimodal processing tasks to complete before exiting, ensuring no data loss from prematurely terminated async tasks.

#### Scenario: Text processing completes before multimodal
- **WHEN** `insert_content_list()` schedules multimodal content as a background task and returns
- **THEN** the subprocess SHALL NOT exit until the background task has completed (success or failure)

#### Scenario: All background tasks complete successfully
- **WHEN** all background multimodal tasks have finished processing
- **THEN** the subprocess SHALL exit with code 0 and the document status SHALL be `processed`

#### Scenario: Background task fails
- **WHEN** a background multimodal task raises an unhandled exception
- **THEN** the subprocess SHALL still wait for it to finish, log the error, and the document status SHALL reflect the failure

### Requirement: Background task registry
The system SHALL maintain a registry of pending background tasks so that the subprocess can discover and await them before exit.

#### Scenario: Task registration
- **WHEN** a background multimodal processing task is created via `asyncio.create_task()`
- **THEN** the task SHALL be registered in a pending-task collection before being scheduled

#### Scenario: Task deregistration on completion
- **WHEN** a registered background task completes (success or failure)
- **THEN** the task SHALL be removed from the pending-task collection in a `finally` block

### Requirement: Maximum wait timeout for background tasks
The subprocess SHALL enforce a maximum wait time for pending background tasks to prevent indefinite hangs caused by stuck VLM/LLM calls.

#### Scenario: Tasks complete within timeout
- **WHEN** all background tasks complete before the maximum wait timeout (default: 30 minutes)
- **THEN** the subprocess SHALL exit normally without triggering the timeout

#### Scenario: Timeout exceeded
- **WHEN** background tasks do not complete within the maximum wait timeout
- **THEN** the subprocess SHALL log a warning with the list of unfinished tasks and exit with code 0, and the document status SHALL be marked as `failed` with a timeout error message
