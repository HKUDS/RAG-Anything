"""Parser management for direct RAG-Anything integration."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from .exceptions import ParserError, ConfigurationError

# Add RAG-Anything to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    from raganything.parser import MineruParser, DoclingParser
    from raganything.config import RAGAnythingConfig
except ImportError as e:
    logger.error(f"Failed to import RAG-Anything modules: {e}")
    # Create placeholder classes for development
    class MineruParser:
        def __init__(self, *args, **kwargs):
            raise ImportError("MineruParser not available")
    
    class DoclingParser:
        def __init__(self, *args, **kwargs):
            raise ImportError("DoclingParser not available")
    
    class RAGAnythingConfig:
        def __init__(self, *args, **kwargs):
            pass


class ParserManager:
    """Manages document parsers for direct integration."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize parser manager.
        
        Args:
            config: Parser configuration dictionary
        """
        self.config = config or {}
        self.parsers = {}
        self._initialize_parsers()
    
    def _initialize_parsers(self) -> None:
        """Initialize available parsers."""
        try:
            # MinerU Parser
            self.parsers["mineru"] = {
                "class": MineruParser,
                "available": self._check_mineru_availability(),
                "supported_formats": [".pdf", ".docx", ".pptx", ".jpg", ".jpeg", ".png"],
                "capabilities": ["ocr", "table_extraction", "image_extraction", "layout_analysis"]
            }
            
            # Docling Parser  
            self.parsers["docling"] = {
                "class": DoclingParser,
                "available": self._check_docling_availability(),
                "supported_formats": [".pdf", ".html", ".docx"],
                "capabilities": ["layout_analysis", "structured_extraction", "markdown_conversion"]
            }
            
            logger.info(f"Initialized {len(self.parsers)} parsers")
            
        except Exception as e:
            logger.error(f"Failed to initialize parsers: {e}")
            raise ConfigurationError(f"Parser initialization failed: {e}")
    
    def _check_mineru_availability(self) -> bool:
        """Check if MinerU parser is available."""
        try:
            # Check if required dependencies are available
            import magic_pdf  # MinerU dependency
            return True
        except ImportError:
            logger.warning("MinerU parser not available - magic_pdf not installed")
            return False
    
    def _check_docling_availability(self) -> bool:
        """Check if Docling parser is available."""
        try:
            import docling  # Docling dependency
            return True
        except ImportError:
            logger.warning("Docling parser not available - docling not installed")
            return False
    
    def get_available_parsers(self) -> Dict[str, Dict[str, Any]]:
        """Get information about available parsers."""
        return {
            name: {
                "available": info["available"],
                "supported_formats": info["supported_formats"],
                "capabilities": info["capabilities"]
            }
            for name, info in self.parsers.items()
        }
    
    def select_parser(
        self, 
        parser_type: str, 
        file_path: str, 
        config: Dict[str, Any] = None
    ) -> str:
        """Select appropriate parser for file.
        
        Args:
            parser_type: Requested parser type ("auto", "mineru", "docling")
            file_path: Path to file to be parsed
            config: Parser configuration
            
        Returns:
            Selected parser name
            
        Raises:
            ParserError: If no suitable parser is available
        """
        if parser_type != "auto":
            # Specific parser requested
            if parser_type not in self.parsers:
                raise ParserError(f"Unknown parser type: {parser_type}")
            
            if not self.parsers[parser_type]["available"]:
                raise ParserError(f"Parser {parser_type} is not available")
            
            return parser_type
        
        # Auto-select parser based on file extension
        file_ext = Path(file_path).suffix.lower()
        
        # Priority: MinerU for PDFs and images, Docling for documents
        if file_ext in [".pdf", ".jpg", ".jpeg", ".png"]:
            if self.parsers["mineru"]["available"]:
                return "mineru"
            elif self.parsers["docling"]["available"] and file_ext == ".pdf":
                return "docling"
        elif file_ext in [".docx", ".html"]:
            if self.parsers["docling"]["available"]:
                return "docling"
            elif self.parsers["mineru"]["available"] and file_ext == ".docx":
                return "mineru"
        
        # Fallback to any available parser
        for name, info in self.parsers.items():
            if info["available"] and file_ext in info["supported_formats"]:
                return name
        
        raise ParserError(f"No available parser for file type: {file_ext}")
    
    async def create_parser_instance(
        self,
        parser_type: str,
        config: Dict[str, Any] = None
    ) -> Union[MineruParser, DoclingParser]:
        """Create parser instance.
        
        Args:
            parser_type: Parser type ("mineru", "docling")
            config: Parser configuration
            
        Returns:
            Parser instance
            
        Raises:
            ParserError: If parser creation fails
        """
        try:
            if parser_type not in self.parsers:
                raise ParserError(f"Unknown parser type: {parser_type}")
            
            parser_info = self.parsers[parser_type]
            
            if not parser_info["available"]:
                raise ParserError(f"Parser {parser_type} is not available")
            
            # Prepare parser configuration
            parser_config = self._prepare_parser_config(parser_type, config or {})
            
            # Create parser instance
            parser_class = parser_info["class"]
            
            if parser_type == "mineru":
                return await self._create_mineru_parser(parser_config)
            elif parser_type == "docling":
                return await self._create_docling_parser(parser_config)
            else:
                raise ParserError(f"Unsupported parser type: {parser_type}")
                
        except Exception as e:
            logger.error(f"Failed to create {parser_type} parser: {e}")
            raise ParserError(f"Parser creation failed: {e}", parser_type)
    
    def _prepare_parser_config(
        self, 
        parser_type: str, 
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare parser configuration.
        
        Args:
            parser_type: Parser type
            config: User provided configuration
            
        Returns:
            Prepared configuration dictionary
        """
        base_config = self.config.get(parser_type, {})
        merged_config = {**base_config, **config}
        
        # Set defaults based on parser type
        if parser_type == "mineru":
            merged_config.setdefault("lang", "en")
            merged_config.setdefault("device", "cpu")
            merged_config.setdefault("enable_image_processing", True)
        elif parser_type == "docling":
            merged_config.setdefault("output_format", "markdown")
            merged_config.setdefault("extract_tables", True)
        
        return merged_config
    
    async def _create_mineru_parser(self, config: Dict[str, Any]) -> MineruParser:
        """Create MinerU parser instance."""
        try:
            # Create MinerU configuration
            mineru_config = RAGAnythingConfig(
                lang=config.get("lang", "en"),
                device=config.get("device", "cpu"),
                **config
            )
            
            # Create parser in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            parser = await loop.run_in_executor(
                None,
                lambda: MineruParser(mineru_config)
            )
            
            logger.info("Created MinerU parser instance")
            return parser
            
        except Exception as e:
            raise ParserError(f"Failed to create MinerU parser: {e}", "mineru")
    
    async def _create_docling_parser(self, config: Dict[str, Any]) -> DoclingParser:
        """Create Docling parser instance."""
        try:
            # Create parser in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            parser = await loop.run_in_executor(
                None,
                lambda: DoclingParser(**config)
            )
            
            logger.info("Created Docling parser instance")
            return parser
            
        except Exception as e:
            raise ParserError(f"Failed to create Docling parser: {e}", "docling")
    
    async def parse_document(
        self,
        file_path: str,
        parser_type: str = "auto",
        config: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """Parse document using appropriate parser.
        
        Args:
            file_path: Path to document file
            parser_type: Parser type to use
            config: Parser configuration
            
        Returns:
            List of parsed content items
            
        Raises:
            ParserError: If parsing fails
        """
        try:
            # Validate file exists
            if not os.path.exists(file_path):
                raise ParserError(f"File not found: {file_path}")
            
            # Select parser
            selected_parser = self.select_parser(parser_type, file_path, config)
            logger.info(f"Using {selected_parser} parser for {file_path}")
            
            # Create parser instance
            parser = await self.create_parser_instance(selected_parser, config)
            
            # Parse document in thread pool
            loop = asyncio.get_event_loop()
            content_items = await loop.run_in_executor(
                None,
                self._parse_with_parser,
                parser,
                file_path,
                selected_parser
            )
            
            logger.info(f"Parsed {len(content_items)} content items from {file_path}")
            return content_items
            
        except ParserError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error parsing {file_path}: {e}")
            raise ParserError(f"Document parsing failed: {e}")
    
    def _parse_with_parser(
        self,
        parser: Union[MineruParser, DoclingParser],
        file_path: str,
        parser_type: str
    ) -> List[Dict[str, Any]]:
        """Parse document with specific parser (synchronous)."""
        try:
            if parser_type == "mineru":
                # Use MinerU parser
                results = parser.parse(file_path)
                return self._format_mineru_results(results)
            elif parser_type == "docling":
                # Use Docling parser
                results = parser.parse(file_path)
                return self._format_docling_results(results)
            else:
                raise ParserError(f"Unknown parser type: {parser_type}")
                
        except Exception as e:
            raise ParserError(f"Parser execution failed: {e}", parser_type)
    
    def _format_mineru_results(self, results: Any) -> List[Dict[str, Any]]:
        """Format MinerU parsing results."""
        content_items = []
        
        try:
            # Convert MinerU results to standard format
            if hasattr(results, 'content_list'):
                for item in results.content_list:
                    content_items.append({
                        "content_type": item.get("type", "text"),
                        "content_data": item.get("data", ""),
                        "metadata": item.get("metadata", {}),
                        "page_number": item.get("page", None),
                        "bbox": item.get("bbox", None)
                    })
            
            return content_items
            
        except Exception as e:
            logger.error(f"Failed to format MinerU results: {e}")
            return []
    
    def _format_docling_results(self, results: Any) -> List[Dict[str, Any]]:
        """Format Docling parsing results."""
        content_items = []
        
        try:
            # Convert Docling results to standard format
            if hasattr(results, 'elements'):
                for element in results.elements:
                    content_items.append({
                        "content_type": element.get("type", "text"),
                        "content_data": element.get("content", ""),
                        "metadata": element.get("metadata", {}),
                        "page_number": element.get("page", None),
                        "bbox": element.get("bbox", None)
                    })
            
            return content_items
            
        except Exception as e:
            logger.error(f"Failed to format Docling results: {e}")
            return []