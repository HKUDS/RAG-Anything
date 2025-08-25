"""Modal processor management for direct RAG-Anything integration."""

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from .exceptions import ProcessorError, ConfigurationError

# Add RAG-Anything to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    from raganything.modalprocessors import (
        ImageModalProcessor,
        TableModalProcessor,
        EquationModalProcessor,
        GenericModalProcessor
    )
except ImportError as e:
    logger.error(f"Failed to import modal processors: {e}")
    # Create placeholder classes for development
    class ImageModalProcessor:
        def __init__(self, *args, **kwargs):
            raise ImportError("ImageModalProcessor not available")
    
    class TableModalProcessor:
        def __init__(self, *args, **kwargs):
            raise ImportError("TableModalProcessor not available")
    
    class EquationModalProcessor:
        def __init__(self, *args, **kwargs):
            raise ImportError("EquationModalProcessor not available")
    
    class GenericModalProcessor:
        def __init__(self, *args, **kwargs):
            raise ImportError("GenericModalProcessor not available")


class ProcessorManager:
    """Manages modal processors for content enhancement."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize processor manager.
        
        Args:
            config: Processor configuration dictionary
        """
        self.config = config or {}
        self.processors = {}
        self._initialize_processors()
    
    def _initialize_processors(self) -> None:
        """Initialize available modal processors."""
        try:
            # Image Modal Processor
            self.processors["image"] = {
                "class": ImageModalProcessor,
                "available": self._check_image_processor_availability(),
                "content_types": ["image"],
                "capabilities": ["image_analysis", "text_extraction", "object_detection"]
            }
            
            # Table Modal Processor
            self.processors["table"] = {
                "class": TableModalProcessor,
                "available": self._check_table_processor_availability(),
                "content_types": ["table"],
                "capabilities": ["table_analysis", "structure_extraction", "data_validation"]
            }
            
            # Equation Modal Processor
            self.processors["equation"] = {
                "class": EquationModalProcessor,
                "available": self._check_equation_processor_availability(),
                "content_types": ["equation"],
                "capabilities": ["math_parsing", "latex_conversion", "formula_analysis"]
            }
            
            # Generic Modal Processor
            self.processors["generic"] = {
                "class": GenericModalProcessor,
                "available": True,  # Always available as fallback
                "content_types": ["text", "image", "table", "equation"],
                "capabilities": ["content_analysis", "metadata_extraction"]
            }
            
            logger.info(f"Initialized {len(self.processors)} modal processors")
            
        except Exception as e:
            logger.error(f"Failed to initialize processors: {e}")
            raise ConfigurationError(f"Processor initialization failed: {e}")
    
    def _check_image_processor_availability(self) -> bool:
        """Check if image processor is available."""
        try:
            # Check for required vision libraries
            import cv2
            import PIL
            return True
        except ImportError:
            logger.warning("Image processor not available - missing vision dependencies")
            return False
    
    def _check_table_processor_availability(self) -> bool:
        """Check if table processor is available."""
        try:
            # Check for required table processing libraries
            import pandas as pd
            return True
        except ImportError:
            logger.warning("Table processor not available - missing pandas")
            return False
    
    def _check_equation_processor_availability(self) -> bool:
        """Check if equation processor is available."""
        try:
            # Check for math processing libraries
            import sympy
            return True
        except ImportError:
            logger.warning("Equation processor not available - missing sympy")
            return False
    
    def get_available_processors(self) -> Dict[str, Dict[str, Any]]:
        """Get information about available processors."""
        return {
            name: {
                "available": info["available"],
                "content_types": info["content_types"],
                "capabilities": info["capabilities"]
            }
            for name, info in self.processors.items()
        }
    
    def select_processor(
        self,
        content_type: str,
        processor_type: str = "auto"
    ) -> str:
        """Select appropriate processor for content type.
        
        Args:
            content_type: Type of content ("image", "table", "equation", "text")
            processor_type: Specific processor type or "auto"
            
        Returns:
            Selected processor name
            
        Raises:
            ProcessorError: If no suitable processor is available
        """
        if processor_type != "auto":
            # Specific processor requested
            if processor_type not in self.processors:
                raise ProcessorError(f"Unknown processor type: {processor_type}")
            
            if not self.processors[processor_type]["available"]:
                raise ProcessorError(f"Processor {processor_type} is not available")
            
            if content_type not in self.processors[processor_type]["content_types"]:
                raise ProcessorError(
                    f"Processor {processor_type} does not support content type: {content_type}"
                )
            
            return processor_type
        
        # Auto-select processor based on content type
        if content_type == "image":
            if self.processors["image"]["available"]:
                return "image"
        elif content_type == "table":
            if self.processors["table"]["available"]:
                return "table"
        elif content_type == "equation":
            if self.processors["equation"]["available"]:
                return "equation"
        
        # Fallback to generic processor
        if self.processors["generic"]["available"]:
            return "generic"
        
        raise ProcessorError(f"No available processor for content type: {content_type}")
    
    async def create_processor_instance(
        self,
        processor_type: str,
        config: Dict[str, Any] = None
    ) -> Union[ImageModalProcessor, TableModalProcessor, EquationModalProcessor, GenericModalProcessor]:
        """Create processor instance.
        
        Args:
            processor_type: Processor type
            config: Processor configuration
            
        Returns:
            Processor instance
            
        Raises:
            ProcessorError: If processor creation fails
        """
        try:
            if processor_type not in self.processors:
                raise ProcessorError(f"Unknown processor type: {processor_type}")
            
            processor_info = self.processors[processor_type]
            
            if not processor_info["available"]:
                raise ProcessorError(f"Processor {processor_type} is not available")
            
            # Prepare processor configuration
            processor_config = self._prepare_processor_config(processor_type, config or {})
            
            # Create processor instance in thread pool
            loop = asyncio.get_event_loop()
            processor_class = processor_info["class"]
            
            processor = await loop.run_in_executor(
                None,
                lambda: processor_class(**processor_config)
            )
            
            logger.info(f"Created {processor_type} processor instance")
            return processor
            
        except Exception as e:
            logger.error(f"Failed to create {processor_type} processor: {e}")
            raise ProcessorError(f"Processor creation failed: {e}", processor_type)
    
    def _prepare_processor_config(
        self,
        processor_type: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare processor configuration.
        
        Args:
            processor_type: Processor type
            config: User provided configuration
            
        Returns:
            Prepared configuration dictionary
        """
        base_config = self.config.get(processor_type, {})
        merged_config = {**base_config, **config}
        
        # Set defaults based on processor type
        if processor_type == "image":
            merged_config.setdefault("enable_ocr", True)
            merged_config.setdefault("enable_object_detection", True)
        elif processor_type == "table":
            merged_config.setdefault("extract_structure", True)
            merged_config.setdefault("validate_data", True)
        elif processor_type == "equation":
            merged_config.setdefault("output_format", "latex")
            merged_config.setdefault("parse_symbols", True)
        
        return merged_config
    
    async def process_content(
        self,
        content_type: str,
        content_data: Any,
        processor_type: str = "auto",
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Process content with appropriate modal processor.
        
        Args:
            content_type: Type of content
            content_data: Content data to process
            processor_type: Processor type to use
            config: Processor configuration
            
        Returns:
            Processed content with enhanced metadata
            
        Raises:
            ProcessorError: If processing fails
        """
        try:
            # Select processor
            selected_processor = self.select_processor(content_type, processor_type)
            logger.info(f"Using {selected_processor} processor for {content_type} content")
            
            # Create processor instance
            processor = await self.create_processor_instance(selected_processor, config)
            
            # Process content in thread pool
            loop = asyncio.get_event_loop()
            processed_content = await loop.run_in_executor(
                None,
                self._process_with_processor,
                processor,
                content_data,
                content_type,
                selected_processor
            )
            
            logger.info(f"Successfully processed {content_type} content")
            return processed_content
            
        except ProcessorError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error processing {content_type} content: {e}")
            raise ProcessorError(f"Content processing failed: {e}")
    
    def _process_with_processor(
        self,
        processor: Union[ImageModalProcessor, TableModalProcessor, EquationModalProcessor, GenericModalProcessor],
        content_data: Any,
        content_type: str,
        processor_type: str
    ) -> Dict[str, Any]:
        """Process content with specific processor (synchronous)."""
        try:
            if processor_type == "image":
                return self._process_image_content(processor, content_data)
            elif processor_type == "table":
                return self._process_table_content(processor, content_data)
            elif processor_type == "equation":
                return self._process_equation_content(processor, content_data)
            elif processor_type == "generic":
                return self._process_generic_content(processor, content_data, content_type)
            else:
                raise ProcessorError(f"Unknown processor type: {processor_type}")
                
        except Exception as e:
            raise ProcessorError(f"Processor execution failed: {e}", processor_type)
    
    def _process_image_content(
        self,
        processor: ImageModalProcessor,
        content_data: Any
    ) -> Dict[str, Any]:
        """Process image content."""
        try:
            result = processor.process(content_data)
            
            return {
                "content_type": "image",
                "content_data": content_data,
                "enhanced_data": result,
                "metadata": {
                    "processor": "image",
                    "extracted_text": result.get("text", ""),
                    "objects_detected": result.get("objects", []),
                    "confidence_scores": result.get("scores", {}),
                    "image_properties": result.get("properties", {})
                }
            }
            
        except Exception as e:
            raise ProcessorError(f"Image processing failed: {e}", "image")
    
    def _process_table_content(
        self,
        processor: TableModalProcessor,
        content_data: Any
    ) -> Dict[str, Any]:
        """Process table content."""
        try:
            result = processor.process(content_data)
            
            return {
                "content_type": "table",
                "content_data": content_data,
                "enhanced_data": result,
                "metadata": {
                    "processor": "table",
                    "structure": result.get("structure", {}),
                    "row_count": result.get("rows", 0),
                    "column_count": result.get("columns", 0),
                    "data_types": result.get("types", {}),
                    "validation_results": result.get("validation", {})
                }
            }
            
        except Exception as e:
            raise ProcessorError(f"Table processing failed: {e}", "table")
    
    def _process_equation_content(
        self,
        processor: EquationModalProcessor,
        content_data: Any
    ) -> Dict[str, Any]:
        """Process equation content."""
        try:
            result = processor.process(content_data)
            
            return {
                "content_type": "equation",
                "content_data": content_data,
                "enhanced_data": result,
                "metadata": {
                    "processor": "equation",
                    "latex_format": result.get("latex", ""),
                    "math_type": result.get("type", ""),
                    "variables": result.get("variables", []),
                    "complexity_score": result.get("complexity", 0)
                }
            }
            
        except Exception as e:
            raise ProcessorError(f"Equation processing failed: {e}", "equation")
    
    def _process_generic_content(
        self,
        processor: GenericModalProcessor,
        content_data: Any,
        content_type: str
    ) -> Dict[str, Any]:
        """Process content with generic processor."""
        try:
            result = processor.process(content_data, content_type=content_type)
            
            return {
                "content_type": content_type,
                "content_data": content_data,
                "enhanced_data": result,
                "metadata": {
                    "processor": "generic",
                    "analysis": result.get("analysis", {}),
                    "features": result.get("features", []),
                    "confidence": result.get("confidence", 0.0)
                }
            }
            
        except Exception as e:
            raise ProcessorError(f"Generic processing failed: {e}", "generic")
    
    async def process_content_batch(
        self,
        content_items: List[Dict[str, Any]],
        processor_configs: Dict[str, Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Process multiple content items in parallel.
        
        Args:
            content_items: List of content items to process
            processor_configs: Configuration for each processor type
            
        Returns:
            List of processed content items
        """
        try:
            configs = processor_configs or {}
            
            # Process items concurrently
            tasks = []
            for item in content_items:
                content_type = item.get("content_type", "text")
                content_data = item.get("content_data")
                
                if content_data is not None:
                    config = configs.get(content_type, {})
                    task = self.process_content(
                        content_type=content_type,
                        content_data=content_data,
                        config=config
                    )
                    tasks.append(task)
                else:
                    # Skip items without content data
                    tasks.append(asyncio.coroutine(lambda: item)())
            
            # Wait for all processing to complete
            processed_items = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle exceptions
            results = []
            for i, result in enumerate(processed_items):
                if isinstance(result, Exception):
                    logger.error(f"Failed to process item {i}: {result}")
                    # Return original item with error metadata
                    error_item = content_items[i].copy()
                    error_item["metadata"] = error_item.get("metadata", {})
                    error_item["metadata"]["processing_error"] = str(result)
                    results.append(error_item)
                else:
                    results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Batch processing failed: {e}")
            raise ProcessorError(f"Batch content processing failed: {e}")