## ADDED Requirements

### Requirement: Safe Expression Evaluation
The system SHALL provide a Calculator tool that evaluates mathematical expressions safely using a whitelist-based restricted `eval()`.

#### Scenario: Basic arithmetic
- **WHEN** Calculator is called with expression "123 * 456 + 789"
- **THEN** the system returns the correct computed result "56877"

#### Scenario: Math functions
- **WHEN** Calculator is called with expression "sqrt(144) + pow(2, 10)"
- **THEN** the system returns "1036.0"

#### Scenario: Malicious input blocked
- **WHEN** Calculator is called with expression containing "__import__", "exec(", or "open("
- **THEN** the system returns an error "表达式包含不允许的操作" without executing

#### Scenario: Invalid expression
- **WHEN** Calculator is called with expression "1/0"
- **THEN** the system catches the ZeroDivisionError and returns "计算错误: division by zero"

#### Scenario: Whitespace and formatting
- **WHEN** Calculator is called with expression containing extra whitespace "  2  +  3  "
- **THEN** the system trims and successfully evaluates to "5"
