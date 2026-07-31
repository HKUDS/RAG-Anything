## MODIFIED Requirements

### Requirement: Subprocess waits for background tasks before exit
The document processing subprocess (`process_worker.py`) SHALL wait for all pending background multimodal processing tasks to complete before exiting, ensuring no data loss from prematurely terminated async tasks. When the owning upload enters `cancelling`, the parent service SHALL stop the subprocess and SHALL prevent its exit result from publishing completion, failure, or automatic retry state.

#### Scenario: Text processing completes before multimodal
- **WHEN** `insert_content_list()` schedules multimodal content as a background task and returns
- **THEN** the subprocess SHALL NOT exit until the background task has completed (success or failure)

#### Scenario: All background tasks complete successfully
- **WHEN** all background tasks complete successfully
- **THEN** the subprocess SHALL exit with code 0 and the document status SHALL be `processed`

#### Scenario: Background task fails
- **WHEN** a background multimodal task raises an unhandled exception
- **THEN** the subprocess SHALL still wait for it to finish, log the error, and the document status SHALL reflect the failure

#### Scenario: Parent cancels the upload
- **WHEN** the parent service transitions the owning upload to `cancelling`
- **THEN** it SHALL stop the matching subprocess and SHALL not publish a completed, failed, or retryable outcome from that subprocess
