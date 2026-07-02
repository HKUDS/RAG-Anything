## ADDED Requirements

### Requirement: Standardized module header comments
Every `.py` file in the `raganything/` package SHALL begin with a standardized header comment block documenting: module name, primary responsibility, layer (Router/Service/Core/Infrastructure), and key dependencies.

#### Scenario: Reading an unfamiliar module
- **WHEN** an AI tool or developer opens any `.py` file in `raganything/`
- **THEN** the first 5 lines SHALL clearly state the module's role, its architectural layer, and its primary imports/consumers

### Requirement: Explicit export lists
Every `__init__.py` file SHALL define `__all__` with the complete public API surface of its sub-package. No implicit exports via wildcard imports SHALL exist.

#### Scenario: Understanding package surface
- **WHEN** an AI tool reads `raganything/services/__init__.py`
- **THEN** `__all__` SHALL list every public function, class, and constant intended for external consumption

### Requirement: Type annotations completeness
All public functions and methods SHALL have complete type annotations for parameters and return values. Internal/private functions SHALL have type annotations where clarity benefits AI comprehension.

#### Scenario: AI tool traces a function call
- **WHEN** an AI tool encounters a function definition
- **THEN** all parameter types and the return type SHALL be explicitly annotated, enabling immediate understanding of data flow without reading the function body

### Requirement: Mixin contract documentation via Protocol
Every Mixin class SHALL have a corresponding Protocol definition that documents its required attributes (`self.config`, `self.lightrag`, `self.logger`, etc.).

#### Scenario: AI tool encounters a Mixin
- **WHEN** an AI tool reads `QueryMixin` and needs to understand what attributes it relies on
- **THEN** the corresponding `QueryCapable` Protocol SHALL list all required attributes with their types, without needing to trace the full class hierarchy

### Requirement: Call chain annotation for complex flows
Modules implementing multi-step workflows (document processing, query pipeline, agentic reasoning) SHALL include a comment at the top documenting the step-by-step call chain.

#### Scenario: Debugging a query failure
- **WHEN** a developer or AI tool needs to trace why a query returned unexpected results
- **THEN** the call chain comment at the top of `query/pipeline.py` SHALL show: `query() → _prepare_context() → _retrieve_chunks() → _rerank() → _build_prompt() → _execute_llm() → _parse_response()`

### Requirement: Consistent language separation
Code comments and docstrings SHALL use English for technical descriptions (parameters, return values, exceptions) and Chinese only for domain-specific business logic explanations where English would lose precision.

#### Scenario: Reading a manufacturing domain comment
- **WHEN** a comment describes a manufacturing-specific concept (e.g., "工艺参数", "故障代码")
- **THEN** the comment MAY use Chinese for the domain term but SHALL include an English translation or explanation in parentheses
