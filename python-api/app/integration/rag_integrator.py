"""Main RAG-Anything integrator for direct Python integration."""

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from .exceptions import RAGIntegrationError, LightRAGError
from .parser_manager import ParserManager
from .processor_manager import ProcessorManager
from .lightrag_config import get_lightrag_config

# Add RAG-Anything to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Import RAG-Anything components with proper error handling
RAG_IMPORTS_AVAILABLE = False
try:
    # Import actual RAG-Anything and LightRAG components
    from raganything import RAGAnything
    from lightrag import LightRAG
    
    # QueryParam is a simple class we can define
    class QueryParam:
        def __init__(self, mode="hybrid", **kwargs):
            self.mode = mode
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    RAG_IMPORTS_AVAILABLE = True
    logger.info("Successfully imported RAG-Anything and LightRAG components")
    
except ImportError as e:
    logger.warning(f"RAG-Anything/LightRAG imports not available: {e}")
    logger.info("Falling back to mock implementations for development")
    
    # Mock classes for development/testing
    class LightRAG:
        def __init__(self, **kwargs):
            self.working_dir = kwargs.get('working_dir', './storage')
            logger.info(f"Mock LightRAG initialized with working_dir: {self.working_dir}")
    
    class RAGAnything:
        def __init__(self, **kwargs):
            logger.info("Mock RAGAnything initialized")
        
        def insert(self, text: str):
            logger.info(f"Mock LightRAG insert: {text[:100]}...")
            return {"status": "mock_inserted", "text_length": len(text)}
        
        def query(self, query: str, param=None):
            logger.info(f"Mock LightRAG query: {query}")
            return f"Mock response for query: {query}"
    
    class QueryParam:
        def __init__(self, mode="hybrid"):
            self.mode = mode


class RAGIntegrator:
    """Main integrator for direct RAG-Anything functionality."""
    
    def __init__(
        self,
        working_dir: str = "./storage",
        lightrag_storage_dir: str = "./lightrag_storage",
        config: Dict[str, Any] = None
    ):
        """Initialize RAG integrator.
        
        Args:
            working_dir: Working directory for file processing
            lightrag_storage_dir: LightRAG storage directory
            config: Integration configuration
        """
        self.working_dir = Path(working_dir)
        self.lightrag_storage_dir = Path(lightrag_storage_dir)
        self.config = config or {}
        
        # Create directories
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.lightrag_storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize components
        self.parser_manager = ParserManager(self.config.get("parsers", {}))
        self.processor_manager = ProcessorManager(self.config.get("processors", {}))
        
        # RAG instances (initialized lazily)
        self._rag_instance = None
        self._lightrag_instance = None
        
        logger.info("RAG integrator initialized")
    
    async def initialize(self) -> None:
        """Initialize RAG components."""
        try:
            await self._initialize_rag_instance()
            await self._initialize_lightrag_instance()
            logger.info("RAG integrator initialization completed")
        except Exception as e:
            logger.error(f"Failed to initialize RAG integrator: {e}")
            raise RAGIntegrationError(f"Initialization failed: {e}")
    
    async def _initialize_rag_instance(self) -> None:
        """Initialize RAG-Anything instance."""
        try:
            if RAG_IMPORTS_AVAILABLE:
                # Import necessary functions from lightrag
                from lightrag.llm.openai import openai_complete_if_cache, openai_embed
                from lightrag.utils import EmbeddingFunc
                from raganything import RAGAnythingConfig
                
                api_key = os.getenv("OPENAI_API_KEY")
                
                # Create RAG-Anything configuration
                rag_config = RAGAnythingConfig(
                    working_dir=str(self.working_dir),
                    parser="mineru",  # Can be changed to "docling" if available
                    parse_method="auto",
                    enable_image_processing=True,
                    enable_table_processing=True,
                    enable_equation_processing=True,
                )
                
                # Define LLM model function
                def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
                    if not api_key:
                        # Fallback to mock if no API key
                        return f"Mock LLM response for: {prompt[:100]}..."
                    return openai_complete_if_cache(
                        "gpt-4o-mini",
                        prompt,
                        system_prompt=system_prompt,
                        history_messages=history_messages,
                        api_key=api_key,
                        **kwargs,
                    )
                
                # Define vision model function
                def vision_model_func(prompt, system_prompt=None, history_messages=[], image_data=None, messages=None, **kwargs):
                    if not api_key:
                        return f"Mock vision response for: {prompt[:100]}..."
                    if messages:
                        return openai_complete_if_cache(
                            "gpt-4o",
                            "",
                            system_prompt=None,
                            history_messages=[],
                            messages=messages,
                            api_key=api_key,
                            **kwargs,
                        )
                    else:
                        return llm_model_func(prompt, system_prompt, history_messages, **kwargs)
                
                # Define embedding function - ensure it's always callable
                if api_key:
                    # Create the embedding function properly
                    def embed_texts(texts):
                        """Embedding function for OpenAI."""
                        return openai_embed(
                            texts,
                            model="text-embedding-3-large",
                            api_key=api_key,
                        )
                    
                    embedding_func = EmbeddingFunc(
                        embedding_dim=3072,
                        max_token_size=8192,
                        func=embed_texts
                    )
                else:
                    # Mock embedding function
                    import numpy as np
                    
                    def mock_embed(texts):
                        """Mock embedding function."""
                        return np.random.randn(len(texts), 3072).tolist()
                    
                    embedding_func = EmbeddingFunc(
                        embedding_dim=3072,
                        max_token_size=8192,
                        func=mock_embed
                    )
                
                # Initialize RAG-Anything with all required components
                self._rag_instance = RAGAnything(
                    config=rag_config,
                    llm_model_func=llm_model_func,
                    vision_model_func=vision_model_func,
                    embedding_func=embedding_func,
                )
                
                logger.info("RAG-Anything instance initialized successfully")
            else:
                logger.info("Using mock RAG instance for development")
                self._rag_instance = "mock_mode"
            
        except Exception as e:
            logger.error(f"Failed to initialize RAG instance: {e}")
            # Fallback to mock mode
            self._rag_instance = "mock_mode"
            logger.info("Falling back to mock RAG instance")
    
    async def _initialize_lightrag_instance(self) -> None:
        """Initialize LightRAG instance."""
        try:
            # Import necessary functions from lightrag
            from lightrag.llm.openai import openai_complete_if_cache, openai_embed
            from lightrag.utils import EmbeddingFunc
            import numpy as np
            
            # Set up environment variable for OpenAI API key
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                os.environ["OPENAI_API_KEY"] = api_key
                logger.info("OpenAI API key configured for LightRAG")
            
            # Define LLM model function for LightRAG
            def llm_model_func(prompt, system_prompt=None, history_messages=[], **kwargs):
                if not api_key:
                    return f"Mock LLM response for: {prompt[:100]}..."
                return openai_complete_if_cache(
                    "gpt-4o-mini",
                    prompt,
                    system_prompt=system_prompt,
                    history_messages=history_messages,
                    api_key=api_key,
                    **kwargs,
                )
            
            # Define embedding function for LightRAG
            def embed_texts(texts):
                if not api_key:
                    return np.random.randn(len(texts), 3072).tolist()
                return openai_embed(
                    texts,
                    model="text-embedding-3-large",
                    api_key=api_key,
                )
            
            embedding_func = EmbeddingFunc(
                embedding_dim=3072,
                max_token_size=8192,
                func=embed_texts
            )
            
            # LightRAG configuration
            lightrag_config = {
                "working_dir": str(self.lightrag_storage_dir),
                "llm_model_func": llm_model_func,
                "embedding_func": embedding_func,
            }
            
            # Add any additional config from settings
            lightrag_config.update(self.config.get("lightrag", {}))
            
            # Create LightRAG instance in thread pool
            loop = asyncio.get_event_loop()
            try:
                self._lightrag_instance = await loop.run_in_executor(
                    None,
                    lambda: LightRAG(**lightrag_config)
                )
                logger.info("LightRAG instance initialized successfully with OpenAI")
            except Exception as lightrag_error:
                logger.warning(f"Could not initialize LightRAG: {lightrag_error}")
                logger.info("Falling back to mock LightRAG for development")
                # Use mock LightRAG as fallback
                self._lightrag_instance = type('MockLightRAG', (), {
                    'insert': lambda self, text: {"status": "mock_inserted", "text_length": len(text)},
                    'query': lambda self, query, **kwargs: f"Mock response for query: {query}",
                    'working_dir': str(self.lightrag_storage_dir)
                })()
            
        except Exception as e:
            logger.warning(f"Failed to initialize LightRAG, using mock: {e}")
            # Use mock LightRAG as fallback
            self._lightrag_instance = type('MockLightRAG', (), {
                'insert': lambda self, text: {"status": "mock_inserted", "text_length": len(text)},
                'query': lambda self, query, **kwargs: f"Mock response for query: {query}",
                'working_dir': str(self.lightrag_storage_dir)
            })()
    
    @property
    async def rag_instance(self) -> "RAGAnything":
        """Get RAG-Anything instance (lazy initialization)."""
        if self._rag_instance is None:
            await self._initialize_rag_instance()
        return self._rag_instance
    
    @property
    async def lightrag_instance(self) -> "LightRAG":
        """Get LightRAG instance (lazy initialization)."""
        if self._lightrag_instance is None:
            await self._initialize_lightrag_instance()
        return self._lightrag_instance
    
    async def process_document(
        self,
        file_path: str,
        parser_type: str = "auto",
        parse_method: str = "auto",
        config: Dict[str, Any] = None,
        enable_multimodal: bool = True
    ) -> Dict[str, Any]:
        """Process document and extract content using RAG-Anything.
        
        Args:
            file_path: Path to document file
            parser_type: Parser type ("auto", "mineru", "docling")
            parse_method: Parse method ("auto", "ocr", "txt", "hybrid")
            config: Processing configuration
            enable_multimodal: Enable multimodal processing
            
        Returns:
            Processing result with document ID and content statistics
        """
        try:
            document_id = str(uuid.uuid4())
            logger.info(f"Processing document {file_path} with ID {document_id}")
            
            # Get RAG-Anything instance
            rag = await self.rag_instance
            
            # If RAG-Anything is properly initialized, use it
            if isinstance(rag, RAGAnything):
                # Use RAG-Anything's process_document_complete method
                output_dir = config.get("output_dir", "./processed_documents") if config else "./processed_documents"
                
                # Create output directory if it doesn't exist
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                
                # Process document using RAG-Anything
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: asyncio.run(rag.process_document_complete(
                        file_path=file_path,
                        output_dir=output_dir,
                        parse_method=parse_method
                    ))
                )
                
                # Format result for API response
                return {
                    "document_id": document_id,
                    "status": "processed",
                    "metadata": {
                        "original_file": file_path,
                        "parser_used": parser_type,
                        "parse_method": parse_method,
                        "multimodal_enabled": enable_multimodal,
                        "output_dir": output_dir
                    }
                }
            else:
                # Fallback to the original parser/processor approach
                content_items = await self.parser_manager.parse_document(
                    file_path=file_path,
                    parser_type=parser_type,
                    config=config or {}
                )
                
                # Process multimodal content if enabled
                if enable_multimodal and content_items:
                    content_items = await self.processor_manager.process_content_batch(
                        content_items=content_items,
                        processor_configs=config.get("processors", {}) if config else {}
                    )
                
                # Calculate statistics
                stats = self._calculate_content_stats(content_items)
                
                # Store in working directory for potential LightRAG insertion
                await self._store_content_items(document_id, content_items, file_path)
                
                result = {
                    "document_id": document_id,
                    "content_items": content_items,
                    "content_stats": stats,
                    "metadata": {
                        "original_file": file_path,
                        "parser_used": parser_type,
                        "parse_method": parse_method,
                        "multimodal_enabled": enable_multimodal
                    }
                }
                
                logger.info(f"Document {document_id} processed successfully")
                return result
            
        except Exception as e:
            logger.error(f"Failed to process document {file_path}: {e}")
            raise RAGIntegrationError(f"Document processing failed: {e}")
    
    async def insert_content_into_lightrag(
        self,
        content_items: List[Dict[str, Any]],
        document_id: str = None
    ) -> Dict[str, Any]:
        """Insert content items into LightRAG knowledge base.
        
        Args:
            content_items: List of content items to insert
            document_id: Document identifier
            
        Returns:
            Insertion result
        """
        try:
            lightrag = await self.lightrag_instance
            
            # Prepare content for LightRAG insertion
            texts_to_insert = []
            for item in content_items:
                content_type = item.get("content_type", "text")
                content_data = item.get("content_data", "")
                
                if content_type == "text" and isinstance(content_data, str):
                    texts_to_insert.append(content_data)
                elif content_type == "table" and isinstance(content_data, dict):
                    # Convert table to text representation
                    table_text = self._table_to_text(content_data)
                    texts_to_insert.append(table_text)
                # Note: Images and equations might need special handling
            
            # Insert into LightRAG in batches
            batch_size = 10
            inserted_count = 0
            
            for i in range(0, len(texts_to_insert), batch_size):
                batch = texts_to_insert[i:i + batch_size]
                batch_text = "\n\n".join(batch)
                
                # Insert batch into LightRAG
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: lightrag.insert(batch_text)
                )
                
                inserted_count += len(batch)
                logger.info(f"Inserted batch {i//batch_size + 1}, total: {inserted_count}")
            
            result = {
                "document_id": document_id,
                "inserted_items": inserted_count,
                "total_items": len(content_items),
                "status": "success"
            }
            
            logger.info(f"Successfully inserted {inserted_count} items into LightRAG")
            return result
            
        except Exception as e:
            logger.error(f"Failed to insert content into LightRAG: {e}")
            raise LightRAGError(f"Content insertion failed: {e}", "insert")
    
    async def query_lightrag(
        self,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10
    ) -> Dict[str, Any]:
        """Query using RAG-Anything or LightRAG.
        
        Args:
            query: Query text
            mode: Query mode ("hybrid", "local", "global", "naive")
            top_k: Maximum number of results
            
        Returns:
            Query results
        """
        try:
            # Try to use RAG-Anything first
            rag = await self.rag_instance
            
            if isinstance(rag, RAGAnything):
                # Use RAG-Anything's aquery method
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: asyncio.run(rag.aquery(query, mode=mode))
                )
            else:
                # Fallback to LightRAG
                lightrag = await self.lightrag_instance
                
                # Create query parameters
                query_param = QueryParam(mode=mode)
                
                # Execute query in thread pool
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: lightrag.query(query, param=query_param)
                )
            
            # Format results
            formatted_result = {
                "query": query,
                "mode": mode,
                "result": result,
                "metadata": {
                    "lightrag_mode": mode,
                    "top_k": top_k
                }
            }
            
            logger.info(f"Query executed successfully: {query[:50]}...")
            return formatted_result
            
        except Exception as e:
            logger.error(f"Failed to query LightRAG: {e}")
            raise LightRAGError(f"Query execution failed: {e}", "query")
    
    async def process_and_insert_document(
        self,
        file_path: str,
        parser_type: str = "auto",
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Process document using RAG-Anything which automatically handles insertion.
        
        Args:
            file_path: Path to document file
            parser_type: Parser type to use
            config: Processing configuration
            
        Returns:
            Combined processing and insertion result
        """
        try:
            # Get RAG-Anything instance
            rag = await self.rag_instance
            
            if isinstance(rag, RAGAnything):
                # RAG-Anything's process_document_complete automatically processes and inserts
                output_dir = config.get("output_dir", "./processed_documents") if config else "./processed_documents"
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                
                document_id = str(uuid.uuid4())
                
                # Process and insert using RAG-Anything
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: asyncio.run(rag.process_document_complete(
                        file_path=file_path,
                        output_dir=output_dir,
                        parse_method="auto"
                    ))
                )
                
                combined_result = {
                    "document_id": document_id,
                    "status": "completed",
                    "message": "Document processed and inserted via RAG-Anything",
                    "metadata": {
                        "file_path": file_path,
                        "output_dir": output_dir
                    }
                }
            else:
                # Fallback to separate process and insert
                process_result = await self.process_document(
                    file_path=file_path,
                    parser_type=parser_type,
                    config=config
                )
                
                # Insert into LightRAG if we have content items
                if "content_items" in process_result:
                    insert_result = await self.insert_content_into_lightrag(
                        content_items=process_result["content_items"],
                        document_id=process_result["document_id"]
                    )
                    
                    combined_result = {
                        "document_id": process_result["document_id"],
                        "processing": process_result,
                        "insertion": insert_result,
                        "status": "completed"
                    }
                else:
                    combined_result = process_result
            
            logger.info(f"Document processed and inserted: {file_path}")
            return combined_result
            
        except Exception as e:
            logger.error(f"Failed to process and insert document: {e}")
            raise RAGIntegrationError(f"Document processing and insertion failed: {e}")
    
    def _calculate_content_stats(self, content_items: List[Dict[str, Any]]) -> Dict[str, int]:
        """Calculate content statistics."""
        stats = {
            "total_items": len(content_items),
            "text_blocks": 0,
            "images": 0,
            "tables": 0,
            "equations": 0,
            "total_pages": 0
        }
        
        pages = set()
        for item in content_items:
            content_type = item.get("content_type", "text")
            stats[f"{content_type}_blocks"] = stats.get(f"{content_type}_blocks", 0) + 1
            
            # Count pages
            page_num = item.get("page_number")
            if page_num:
                pages.add(page_num)
        
        stats["total_pages"] = len(pages)
        return stats
    
    async def _store_content_items(
        self,
        document_id: str,
        content_items: List[Dict[str, Any]],
        original_file: str
    ) -> None:
        """Store content items for later use."""
        try:
            storage_path = self.working_dir / f"{document_id}.json"
            
            storage_data = {
                "document_id": document_id,
                "original_file": original_file,
                "content_items": content_items,
                "created_at": asyncio.get_event_loop().time()
            }
            
            import json
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: storage_path.write_text(json.dumps(storage_data, indent=2))
            )
            
        except Exception as e:
            logger.warning(f"Failed to store content items: {e}")
    
    def _table_to_text(self, table_data: Dict[str, Any]) -> str:
        """Convert table data to text representation."""
        try:
            if "headers" in table_data and "rows" in table_data:
                headers = table_data["headers"]
                rows = table_data["rows"]
                
                # Create markdown table
                header_line = "| " + " | ".join(headers) + " |"
                separator_line = "|" + "---|" * len(headers)
                
                text_lines = [header_line, separator_line]
                
                for row in rows:
                    row_line = "| " + " | ".join(str(cell) for cell in row) + " |"
                    text_lines.append(row_line)
                
                return "\n".join(text_lines)
            else:
                return str(table_data)
                
        except Exception as e:
            logger.warning(f"Failed to convert table to text: {e}")
            return str(table_data)
    
    async def get_knowledge_base_info(self) -> Dict[str, Any]:
        """Get knowledge base information."""
        try:
            # This would need to be implemented based on LightRAG's API
            # For now, return basic info
            return {
                "status": "active",
                "storage_dir": str(self.lightrag_storage_dir),
                "working_dir": str(self.working_dir)
            }
            
        except Exception as e:
            logger.error(f"Failed to get knowledge base info: {e}")
            raise LightRAGError(f"Knowledge base info retrieval failed: {e}")
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        try:
            # Cleanup would depend on RAG-Anything and LightRAG implementation
            logger.info("RAG integrator cleanup completed")
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")