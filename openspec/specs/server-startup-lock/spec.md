# server-startup-lock Specification

## Purpose
TBD - created by archiving change prevent-duplicate-processes. Update Purpose after archive.
## Requirements
### Requirement: Server PID file on startup
The server SHALL create a PID file (`<working_dir>/.server.pid`) on startup containing its process ID and start timestamp. It SHALL refuse to start if a valid PID file exists and the referenced process is still alive.

#### Scenario: First startup creates PID file
- **WHEN** the server starts and no `.server.pid` file exists
- **THEN** the server creates `.server.pid` containing its PID and ISO-8601 timestamp

#### Scenario: Second startup with live PID refuses
- **WHEN** the server starts and `.server.pid` exists with a PID that is alive
- **THEN** the server logs an error and exits with code 1

#### Scenario: Second startup with stale PID proceeds
- **WHEN** the server starts and `.server.pid` exists but the referenced PID is not alive
- **THEN** the server overwrites `.server.pid` with its own PID and starts normally

#### Scenario: Server cleans PID file on graceful shutdown
- **WHEN** the server receives SIGTERM or SIGINT
- **THEN** the server removes `.server.pid` before exiting

### Requirement: Server port pre-check
The server SHALL attempt to bind to its configured port before initializing the full application stack, and exit with a clear error message if the port is already in use.

#### Scenario: Port already bound
- **WHEN** the server starts and the configured port is already in use by another process
- **THEN** the server logs "Port {port} is already in use" and exits with code 1

#### Scenario: Port is free
- **WHEN** the server starts and the configured port is free
- **THEN** the server proceeds with normal initialization

### Requirement: PID file is cleaned on abnormal exit
The server SHALL register an `atexit` handler to remove the PID file, ensuring cleanup even on unexpected crashes (where the Python interpreter still runs cleanup handlers).

#### Scenario: Server crashes after creating PID file
- **WHEN** the server process terminates unexpectedly but Python's atexit handlers execute
- **THEN** the `.server.pid` file is removed

