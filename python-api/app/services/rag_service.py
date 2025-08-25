"""RAG service for document processing and querying."""

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, AsyncGenerator

from loguru import logger

from app.config import settings
from app.integration.rag_integrator import RAGIntegrator
from app.integration.exceptions import RAGIntegrationError, LightRAGError


class RAGService:
    """RAG service for document processing and querying operations."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize RAG service.
        
        Args:
            config: Service configuration
        """
        self.config = config or {}
        self.working_dir = Path(self.config.get('working_dir', settings.raganything.working_dir))
        self.lightrag_dir = Path(self.config.get('lightrag_dir', settings.raganything.lightrag_storage_dir))
        
        # Ensure directories exist
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.lightrag_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize integrator
        self.integrator = RAGIntegrator(
            working_dir=str(self.working_dir),
            lightrag_storage_dir=str(self.lightrag_dir),
            config=self.config
        )
        
        self._initialized = False
        
    async def initialize(self) -> None:
        """Initialize the RAG service."""
        if not self._initialized:
            await self.integrator.initialize()
            self._initialized = True
            logger.info("RAG service initialized")
    
    async def process_document(
        self,
        file_path: str,
        parser_type: str = "auto",
        parse_method: str = "auto",
        config: Dict[str, Any] = None,
        insert_to_kb: bool = True
    ) -> Dict[str, Any]:
        """Process document and optionally insert into knowledge base.
        
        Args:
            file_path: Path to the document file
            parser_type: Parser type to use ("auto", "mineru", "docling")
            parse_method: Parse method ("auto", "ocr", "txt", "hybrid")
            config: Processing configuration
            insert_to_kb: Whether to insert into knowledge base
            
        Returns:
            Processing result with document ID and statistics
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            start_time = datetime.utcnow()
            
            # Process document
            if insert_to_kb:
                result = await self.integrator.process_and_insert_document(
                    file_path=file_path,
                    parser_type=parser_type,
                    config=config or {}
                )
            else:
                result = await self.integrator.process_document(
                    file_path=file_path,
                    parser_type=parser_type,
                    parse_method=parse_method,
                    config=config or {},
                    enable_multimodal=True
                )
            
            processing_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Enhance result with processing metadata
            result.update({
                "processing_time_seconds": processing_time,
                "processed_at": start_time.isoformat(),
                "service_version": "1.0.0",
                "inserted_to_kb": insert_to_kb
            })
            
            logger.info(f"Document processed successfully: {result.get('document_id')}")
            return result
            
        except Exception as e:
            logger.error(f"Document processing failed: {e}")
            raise RAGIntegrationError(f"Document processing failed: {e}")
    
    async def query_text(
        self,
        query: str,
        mode: str = "hybrid",
        kb_id: str = "default",
        top_k: int = 10,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute text-based query.
        
        Args:
            query: Query text
            mode: Query mode ("hybrid", "local", "global", "naive")
            kb_id: Knowledge base identifier (for future multi-KB support)
            top_k: Maximum number of results
            **kwargs: Additional query parameters
            
        Returns:
            Query results
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            # Validate query mode
            valid_modes = ["hybrid", "local", "global", "naive"]
            if mode not in valid_modes:
                raise ValueError(f"Invalid query mode: {mode}. Valid modes: {valid_modes}")
            
            start_time = datetime.utcnow()
            
            # Execute query
            result = await self.integrator.query_lightrag(
                query=query,
                mode=mode,
                top_k=top_k
            )
            
            query_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Enhance result
            result.update({
                "query_time_seconds": query_time,
                "queried_at": start_time.isoformat(),
                "kb_id": kb_id,
                "top_k": top_k,
                **kwargs
            })
            
            logger.info(f"Text query executed successfully: {query[:50]}...")
            return result
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Text query failed: {e}")
            raise LightRAGError(f"Text query failed: {e}")
    
    async def query_multimodal(
        self,
        query: str,
        multimodal_content: List[Dict[str, Any]],
        mode: str = "hybrid",
        kb_id: str = "default"
    ) -> Dict[str, Any]:
        """Execute multimodal query with structured content.
        
        Args:
            query: Query text
            multimodal_content: List of multimodal content items
            mode: Query mode
            kb_id: Knowledge base identifier
            
        Returns:
            Query results with multimodal processing
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            start_time = datetime.utcnow()
            
            # Validate multimodal content
            validated_content = await self._validate_multimodal_content(multimodal_content)
            
            # For now, we'll process multimodal content by converting to text
            # and combining with the original query
            enhanced_query = await self._enhance_query_with_multimodal(query, validated_content)
            
            # Execute the enhanced query
            result = await self.query_text(
                query=enhanced_query,
                mode=mode,
                kb_id=kb_id
            )
            
            query_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Add multimodal-specific metadata
            result.update({
                "multimodal_query": True,
                "multimodal_content_count": len(validated_content),
                "multimodal_content_types": [item.get("type") for item in validated_content],
                "total_query_time_seconds": query_time
            })
            
            logger.info(f"Multimodal query executed: {len(validated_content)} content items")
            return result
            
        except Exception as e:
            logger.error(f"Multimodal query failed: {e}")
            raise LightRAGError(f"Multimodal query failed: {e}")
    
    async def query_vlm_enhanced(
        self,
        query: str,
        mode: str = "hybrid",
        kb_id: str = "default",
        enable_image_analysis: bool = True
    ) -> Dict[str, Any]:
        """Execute VLM-enhanced query with automatic image analysis.
        
        Args:
            query: Query text
            mode: Query mode
            kb_id: Knowledge base identifier
            enable_image_analysis: Whether to enable image analysis
            
        Returns:
            VLM-enhanced query results
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            start_time = datetime.utcnow()
            
            # For now, execute as regular text query
            # This can be enhanced with actual VLM integration later
            result = await self.query_text(
                query=query,
                mode=mode,
                kb_id=kb_id
            )
            
            # Add VLM-specific metadata
            result.update({
                "vlm_enhanced": True,
                "image_analysis_enabled": enable_image_analysis,
                "vlm_processing_note": "VLM enhancement placeholder - will be implemented with full VLM integration"
            })
            
            logger.info("VLM-enhanced query executed (placeholder implementation)")
            return result
            
        except Exception as e:
            logger.error(f"VLM-enhanced query failed: {e}")
            raise LightRAGError(f"VLM-enhanced query failed: {e}")
    
    async def stream_query(
        self,
        query: str,
        mode: str = "hybrid",
        kb_id: str = "default"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream query results for long-running queries.
        
        Args:
            query: Query text
            mode: Query mode
            kb_id: Knowledge base identifier
            
        Yields:
            Query result chunks
        """
        try:
            # Yield initial status
            yield {
                "type": "status",
                "message": "Starting query execution",
                "query": query,
                "mode": mode,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Execute query (for now, we'll simulate streaming)
            result = await self.query_text(query=query, mode=mode, kb_id=kb_id)
            
            # Simulate streaming by chunking the response
            response_text = result.get("result", "")
            chunk_size = 100  # Characters per chunk
            
            for i in range(0, len(response_text), chunk_size):
                chunk = response_text[i:i + chunk_size]
                yield {
                    "type": "content",
                    "chunk": chunk,
                    "chunk_index": i // chunk_size,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                # Small delay to simulate streaming
                await asyncio.sleep(0.1)
            
            # Yield final status with metadata
            yield {
                "type": "complete",
                "metadata": {
                    "query_time": result.get("query_time_seconds"),
                    "mode": mode,
                    "total_chunks": (len(response_text) // chunk_size) + 1
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            yield {
                "type": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def insert_text(
        self,
        text: str,
        document_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Insert text directly into the knowledge base.
        
        Args:
            text: Text content to insert
            document_id: Optional document identifier
            metadata: Additional metadata
            
        Returns:
            Insertion result
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            if not document_id:
                document_id = str(uuid.uuid4())
            
            # Create content items from text
            content_items = [{
                "content_type": "text",
                "content_data": text,
                "metadata": metadata or {},
                "document_id": document_id
            }]
            
            # Insert into LightRAG
            result = await self.integrator.insert_content_into_lightrag(
                content_items=content_items,
                document_id=document_id
            )
            
            logger.info(f"Text inserted successfully: {document_id}")
            return result
            
        except Exception as e:
            logger.error(f"Text insertion failed: {e}")
            raise LightRAGError(f"Text insertion failed: {e}")
    
    async def get_knowledge_base_info(self, kb_id: str = "default") -> Dict[str, Any]:
        """Get knowledge base information.
        
        Args:
            kb_id: Knowledge base identifier
            
        Returns:
            Knowledge base information
        """
        try:
            if not self._initialized:
                await self.initialize()
            
            # Get basic info from integrator
            base_info = await self.integrator.get_knowledge_base_info()
            
            # Add additional metadata
            info = {
                "kb_id": kb_id,
                "status": "active",
                "working_dir": str(self.working_dir),
                "lightrag_dir": str(self.lightrag_dir),
                "service_initialized": self._initialized,
                **base_info
            }
            
            return info
            
        except Exception as e:
            logger.error(f"Failed to get knowledge base info: {e}")
            raise LightRAGError(f"Knowledge base info retrieval failed: {e}")
    
    async def _validate_multimodal_content(self, content_list: List[Dict]) -> List[Dict]:
        """Validate multimodal content structure.
        
        Args:
            content_list: List of multimodal content items
            
        Returns:
            Validated content list
        """
        validated = []
        
        for item in content_list:
            content_type = item.get("type")
            
            if content_type == "image":
                if "image_path" not in item:
                    raise ValueError("Image content must have 'image_path' field")
                
                image_path = item["image_path"]
                if not os.path.isabs(image_path):
                    raise ValueError("Image path must be absolute")
                
                if not os.path.exists(image_path):
                    raise ValueError(f"Image file not found: {image_path}")
                
                validated.append(item)
                
            elif content_type == "table":
                required_fields = ["table_data"]
                for field in required_fields:
                    if field not in item:
                        raise ValueError(f"Table content must have '{field}' field")
                
                validated.append(item)
                
            elif content_type == "equation":
                if "equation" not in item:
                    raise ValueError("Equation content must have 'equation' field")
                
                validated.append(item)
                
            else:
                raise ValueError(f"Unsupported content type: {content_type}")
        
        return validated
    
    async def _enhance_query_with_multimodal(
        self,
        query: str,
        multimodal_content: List[Dict]
    ) -> str:
        """Enhance query with multimodal content descriptions.
        
        Args:
            query: Original query text
            multimodal_content: Validated multimodal content
            
        Returns:
            Enhanced query text
        """
        enhanced_parts = [query]
        
        for item in multimodal_content:
            content_type = item.get("type")
            
            if content_type == "image":
                enhanced_parts.append(f"[Image: {item.get('image_path', 'unknown')}]")
            elif content_type == "table":
                table_data = item.get("table_data", "")
                caption = item.get("table_caption", "")
                enhanced_parts.append(f"[Table: {caption}] {table_data}")
            elif content_type == "equation":
                equation = item.get("equation", "")
                enhanced_parts.append(f"[Equation: {equation}]")
        
        return " ".join(enhanced_parts)
    
    async def cleanup(self) -> None:
        """Cleanup service resources."""
        try:
            if self.integrator:
                await self.integrator.cleanup()
            logger.info("RAG service cleanup completed")
        except Exception as e:
            logger.warning(f"RAG service cleanup failed: {e}")


# Global service instance (initialized in main.py)
rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """Get global RAG service instance."""
    if rag_service is None:
        raise RuntimeError("RAG service not initialized")
    return rag_service