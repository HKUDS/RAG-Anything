## MODIFIED Requirements

### Requirement: Queue drain processes files sequentially
A single drain coroutine per KB SHALL process files from the queue one at a time. The drain SHALL be started automatically when the first file is added to an empty queue, and SHALL exit when the queue becomes empty. The drain SHALL not claim, process, or requeue an upload whose durable status is `cancelling` or `deleted`.

#### Scenario: Drain starts on first file
- **WHEN** a file is added to an empty queue for KB "X"
- **THEN** the drain coroutine starts automatically and begins processing the file

#### Scenario: Sequential processing
- **WHEN** files [A, B, C] are in KB "X"'s queue with `max_concurrent_files` = 1
- **THEN** file A is processed first, then B, then C — never two at once

#### Scenario: Next file starts after completion
- **WHEN** file A completes processing (worker exits with code 0)
- **THEN** file B's processing begins automatically

#### Scenario: Next file starts after failure
- **WHEN** file A fails during processing (worker exits with non-zero code)
- **THEN** file B's processing begins automatically

#### Scenario: Next file starts after cancellation
- **WHEN** file A is cancelled before its worker can be claimed or while the queue is draining
- **THEN** the drain SHALL discard A without processing it and continue with the next eligible task

#### Scenario: Drain exits on empty queue
- **WHEN** the last file in the queue completes processing
- **THEN** the drain coroutine exits, and the KB's queue returns to idle state
