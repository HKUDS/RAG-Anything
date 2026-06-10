## ADDED Requirements

### Requirement: Web Search Execution
The system SHALL provide a WebSearch tool that queries an external search provider and returns structured results (title, snippet, URL).

#### Scenario: Successful DuckDuckGo search
- **WHEN** WebSearch is called with query "Python 3.12 release notes"
- **THEN** the system returns a list of up to 5 results, each containing `title`, `snippet`, and `url`

#### Scenario: Empty search results
- **WHEN** WebSearch returns no results for the query
- **THEN** the system returns "未找到相关搜索结果"

#### Scenario: Search provider unavailable
- **WHEN** the configured search provider is unreachable (network error, timeout)
- **THEN** the system returns "搜索服务暂时不可用，请稍后重试" without crashing

#### Scenario: Rate limiting
- **WHEN** more than 10 search requests are made within 60 seconds
- **THEN** the system SHALL return "搜索请求过于频繁，请稍后再试"

### Requirement: Pluggable Search Providers
The WebSearch tool SHALL support multiple search backends via a provider interface, defaulting to DuckDuckGo (no API key required).

#### Scenario: Default provider (DuckDuckGo)
- **WHEN** no search provider is configured
- **THEN** the system uses DuckDuckGo Instant Answer API

#### Scenario: Custom SearXNG provider
- **WHEN** SEARXNG_URL environment variable is set
- **THEN** the system uses the SearXNG instance at that URL for all search queries
