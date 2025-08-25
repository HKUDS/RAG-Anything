"""Integration layer exceptions."""


class RAGIntegrationError(Exception):
    """Base exception for RAG integration errors."""
    
    def __init__(self, message: str, error_code: str = "RAG_INTEGRATION_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class ParserError(RAGIntegrationError):
    """Exception for document parsing errors."""
    
    def __init__(self, message: str, parser_type: str = None):
        self.parser_type = parser_type
        super().__init__(message, "PARSER_ERROR")


class ProcessorError(RAGIntegrationError):
    """Exception for content processing errors."""
    
    def __init__(self, message: str, processor_type: str = None):
        self.processor_type = processor_type
        super().__init__(message, "PROCESSOR_ERROR")


class LightRAGError(RAGIntegrationError):
    """Exception for LightRAG operations."""
    
    def __init__(self, message: str, operation: str = None):
        self.operation = operation
        super().__init__(message, "LIGHTRAG_ERROR")


class ConfigurationError(RAGIntegrationError):
    """Exception for configuration errors."""
    
    def __init__(self, message: str, config_key: str = None):
        self.config_key = config_key
        super().__init__(message, "CONFIGURATION_ERROR")


class ResourceError(RAGIntegrationError):
    """Exception for resource availability errors."""
    
    def __init__(self, message: str, resource_type: str = None):
        self.resource_type = resource_type
        super().__init__(message, "RESOURCE_ERROR")