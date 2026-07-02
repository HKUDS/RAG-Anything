## ADDED Requirements

### Requirement: Dependency direction enforcement
The system SHALL enforce a strict top-down dependency direction across four architectural layers: Router → Service → Core → Infrastructure. No module SHALL import from a layer above its own.

#### Scenario: Router imports from Core
- **WHEN** a module in `raganything/routers/` imports from `raganything/` core modules
- **THEN** the import SHALL go through a Service layer module, not directly to Core internals

#### Scenario: Core does not import from Router
- **WHEN** any module in the Core layer attempts to import from `raganything/routers/`
- **THEN** the system SHALL flag this as an architecture violation requiring refactoring

#### Scenario: Infrastructure does not import from upper layers
- **WHEN** any module in the Infrastructure layer imports from Router, Service, or Core layers
- **THEN** the system SHALL flag this as an architecture violation

### Requirement: No root-level modules imported by package internals
All importable modules SHALL reside within the `raganything/` package. No module inside `raganything/` SHALL import from root-level `.py` files outside the package.

#### Scenario: Package module imports auth
- **WHEN** `raganything/dependencies.py` needs authentication utilities
- **THEN** it SHALL import from `raganything.services.auth` instead of root-level `auth.py`

#### Scenario: Root-level backward compatibility
- **WHEN** external scripts need to import `auth` or `agent_manager`
- **THEN** root-level wrapper files SHALL re-export from `raganything.services.*` to maintain backward compatibility

### Requirement: Eliminate duplicate definitions
No business logic function or class SHALL be defined in more than one module. The system SHALL have exactly one canonical definition for `get_current_user`, `Limiter` instances, and KB management functions.

#### Scenario: Single get_current_user definition
- **WHEN** any router needs to authenticate a user
- **THEN** it SHALL import `get_current_user` from exactly one source: `raganything.dependencies`

#### Scenario: Single Limiter instance
- **WHEN** rate limiting is applied to any endpoint
- **THEN** there SHALL be exactly one `slowapi.Limiter` instance shared across all routers

### Requirement: Explicit public API per package
Each sub-package's `__init__.py` SHALL explicitly declare its public API surface via `__all__`. No backward-compatibility re-exports from unrelated sub-packages SHALL exist in `__init__.py` files.

#### Scenario: processor/__init__.py clean exports
- **WHEN** `raganything/processor/__init__.py` is imported
- **THEN** it SHALL NOT import from `raganything.parser` or `raganything.utils` solely for backward compatibility re-exports
