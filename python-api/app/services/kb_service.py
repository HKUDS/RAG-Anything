"""Knowledge base management service."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from loguru import logger

from app.config import settings
from app.integration.rag_integrator import RAGIntegrator
from app.integration.exceptions import RAGIntegrationError, LightRAGError


class KnowledgeBaseService:
    """Service for managing knowledge bases."""
    
    def __init__(self, base_storage_dir: str = None):
        """Initialize knowledge base service.
        
        Args:
            base_storage_dir: Base directory for knowledge base storage
        """
        self.base_storage_dir = Path(base_storage_dir or settings.raganything.lightrag_storage_dir)
        self.base_storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Active knowledge base integrators
        self._active_kbs: Dict[str, RAGIntegrator] = {}
        
        logger.info(f"Knowledge base service initialized with storage: {self.base_storage_dir}")
    
    async def create_knowledge_base(
        self,
        kb_id: str,
        name: str = None,
        description: str = None,
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Create new knowledge base with isolated storage.
        
        Args:
            kb_id: Knowledge base identifier
            name: Human-readable name
            description: Knowledge base description
            config: Configuration parameters
            
        Returns:
            Knowledge base metadata
        """
        try:
            kb_dir = self.base_storage_dir / kb_id
            
            if kb_dir.exists():
                raise ValueError(f"Knowledge base '{kb_id}' already exists")
            
            # Validate kb_id
            if not kb_id.replace('_', '').replace('-', '').isalnum():
                raise ValueError("KB ID must contain only alphanumeric characters, hyphens, and underscores")
            
            if len(kb_id) < 3 or len(kb_id) > 64:
                raise ValueError("KB ID must be between 3 and 64 characters")
            
            # Create knowledge base directory
            kb_dir.mkdir(parents=True)
            
            # Initialize configuration
            kb_config = {
                'working_dir': str(kb_dir / 'working'),
                'lightrag_dir': str(kb_dir / 'lightrag'),
                **(config or {})
            }
            
            # Create RAG integrator for this KB
            integrator = RAGIntegrator(
                working_dir=kb_config['working_dir'],
                lightrag_storage_dir=kb_config['lightrag_dir'],
                config=kb_config
            )
            
            # Initialize the integrator
            await integrator.initialize()
            
            # Store in active KBs
            self._active_kbs[kb_id] = integrator
            
            # Create metadata
            metadata = {
                "kb_id": kb_id,
                "name": name or kb_id,
                "description": description or f"Knowledge base {kb_id}",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "config": kb_config,
                "document_count": 0,
                "total_size_bytes": 0,
                "status": "active",
                "version": "1.0.0"
            }
            
            # Save metadata
            metadata_file = kb_dir / "metadata.json"
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"Knowledge base '{kb_id}' created successfully")
            return metadata
            
        except ValueError:
            raise
        except Exception as e:
            # Cleanup on failure
            if kb_dir.exists():
                shutil.rmtree(kb_dir, ignore_errors=True)
            
            # Remove from active KBs if added
            if kb_id in self._active_kbs:
                del self._active_kbs[kb_id]
            
            logger.error(f"Failed to create knowledge base '{kb_id}': {e}")
            raise RAGIntegrationError(f"Failed to create knowledge base: {e}")
    
    async def get_knowledge_base_info(self, kb_id: str) -> Dict[str, Any]:
        """Get knowledge base information and statistics.
        
        Args:
            kb_id: Knowledge base identifier
            
        Returns:
            Knowledge base information
        """
        try:
            kb_dir = self.base_storage_dir / kb_id
            
            if not kb_dir.exists():
                raise ValueError(f"Knowledge base '{kb_id}' not found")
            
            # Load metadata
            metadata_file = kb_dir / "metadata.json"
            if not metadata_file.exists():
                raise ValueError(f"Knowledge base '{kb_id}' metadata corrupted")
            
            with open(metadata_file, "r") as f:
                metadata = json.load(f)
            
            # Calculate current statistics
            stats = await self._calculate_kb_statistics(kb_dir)
            
            # Update metadata with current stats
            metadata.update({
                "document_count": stats["document_count"],
                "total_size_bytes": stats["total_size_bytes"],
                "total_size_mb": stats["total_size_mb"],
                "file_count": stats["file_count"],
                "last_accessed": datetime.utcnow().isoformat(),
                "is_loaded": kb_id in self._active_kbs
            })
            
            return metadata
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to get knowledge base info for '{kb_id}': {e}")
            raise RAGIntegrationError(f"Failed to get knowledge base info: {e}")
    
    async def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        """List all knowledge bases.
        
        Returns:
            List of knowledge base metadata
        """
        try:
            knowledge_bases = []
            
            if not self.base_storage_dir.exists():
                return knowledge_bases
            
            for kb_dir in self.base_storage_dir.iterdir():
                if kb_dir.is_dir():
                    metadata_file = kb_dir / "metadata.json"
                    
                    if metadata_file.exists():
                        try:
                            with open(metadata_file, "r") as f:
                                metadata = json.load(f)
                            
                            # Add basic stats
                            stats = await self._calculate_kb_statistics(kb_dir)
                            metadata.update({
                                "document_count": stats["document_count"],
                                "total_size_mb": stats["total_size_mb"],
                                "is_loaded": kb_dir.name in self._active_kbs,
                                "last_accessed": metadata.get("updated_at", metadata.get("created_at"))
                            })
                            
                            knowledge_bases.append(metadata)
                            
                        except Exception as e:
                            logger.warning(f"Failed to load metadata for KB '{kb_dir.name}': {e}")
                            # Add minimal metadata for corrupted KB
                            knowledge_bases.append({
                                "kb_id": kb_dir.name,
                                "name": kb_dir.name,
                                "status": "corrupted",
                                "error": str(e)
                            })
            
            # Sort by creation date
            knowledge_bases.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            
            return knowledge_bases
            
        except Exception as e:
            logger.error(f"Failed to list knowledge bases: {e}")
            raise RAGIntegrationError(f"Failed to list knowledge bases: {e}")
    
    async def update_knowledge_base(
        self,
        kb_id: str,
        name: str = None,
        description: str = None,
        config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Update knowledge base metadata.
        
        Args:
            kb_id: Knowledge base identifier
            name: New name
            description: New description
            config: Configuration updates
            
        Returns:
            Updated metadata
        """
        try:
            kb_dir = self.base_storage_dir / kb_id
            
            if not kb_dir.exists():
                raise ValueError(f"Knowledge base '{kb_id}' not found")
            
            # Load existing metadata
            metadata_file = kb_dir / "metadata.json"
            with open(metadata_file, "r") as f:
                metadata = json.load(f)
            
            # Update fields
            if name is not None:
                metadata["name"] = name
            
            if description is not None:
                metadata["description"] = description
            
            if config is not None:
                metadata["config"].update(config)
            
            metadata["updated_at"] = datetime.utcnow().isoformat()
            
            # Save updated metadata
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)
            
            # If KB is loaded, update the integrator config
            if kb_id in self._active_kbs and config:
                # Note: Some config changes might require reinitialization
                logger.info(f"Knowledge base '{kb_id}' configuration updated")
            
            logger.info(f"Knowledge base '{kb_id}' metadata updated")
            return metadata
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to update knowledge base '{kb_id}': {e}")
            raise RAGIntegrationError(f"Failed to update knowledge base: {e}")
    
    async def delete_knowledge_base(self, kb_id: str, force: bool = False) -> Dict[str, Any]:
        """Delete knowledge base and cleanup storage.
        
        Args:
            kb_id: Knowledge base identifier
            force: Force deletion even if KB is in use
            
        Returns:
            Deletion result
        """
        try:
            kb_dir = self.base_storage_dir / kb_id
            
            if not kb_dir.exists():
                raise ValueError(f"Knowledge base '{kb_id}' not found")
            
            # Check if KB is in use (loaded)
            if kb_id in self._active_kbs and not force:
                raise ValueError(f"Knowledge base '{kb_id}' is currently in use. Use force=True to delete anyway")
            
            # Calculate stats before deletion
            stats = await self._calculate_kb_statistics(kb_dir)
            
            # Cleanup active KB if loaded
            if kb_id in self._active_kbs:
                try:
                    await self._active_kbs[kb_id].cleanup()
                except Exception as e:
                    logger.warning(f"Error during KB cleanup: {e}")
                
                del self._active_kbs[kb_id]
            
            # Remove directory
            shutil.rmtree(kb_dir)
            
            deletion_result = {
                "kb_id": kb_id,
                "deleted": True,
                "deleted_at": datetime.utcnow().isoformat(),
                "cleanup_stats": stats
            }
            
            logger.info(f"Knowledge base '{kb_id}' deleted successfully")
            return deletion_result
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete knowledge base '{kb_id}': {e}")
            raise RAGIntegrationError(f"Failed to delete knowledge base: {e}")
    
    async def load_knowledge_base(self, kb_id: str) -> RAGIntegrator:
        """Load knowledge base into memory if not already loaded.
        
        Args:
            kb_id: Knowledge base identifier
            
        Returns:
            RAG integrator instance
        """
        try:
            if kb_id in self._active_kbs:
                return self._active_kbs[kb_id]
            
            kb_dir = self.base_storage_dir / kb_id
            
            if not kb_dir.exists():
                raise ValueError(f"Knowledge base '{kb_id}' not found")
            
            # Load metadata
            metadata_file = kb_dir / "metadata.json"
            with open(metadata_file, "r") as f:
                metadata = json.load(f)
            
            config = metadata.get("config", {})
            
            # Create and initialize integrator
            integrator = RAGIntegrator(
                working_dir=config.get('working_dir', str(kb_dir / 'working')),
                lightrag_storage_dir=config.get('lightrag_dir', str(kb_dir / 'lightrag')),
                config=config
            )
            
            await integrator.initialize()
            
            # Store in active KBs
            self._active_kbs[kb_id] = integrator
            
            logger.info(f"Knowledge base '{kb_id}' loaded successfully")
            return integrator
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to load knowledge base '{kb_id}': {e}")
            raise RAGIntegrationError(f"Failed to load knowledge base: {e}")
    
    async def unload_knowledge_base(self, kb_id: str) -> bool:
        """Unload knowledge base from memory.
        
        Args:
            kb_id: Knowledge base identifier
            
        Returns:
            True if unloaded successfully
        """
        try:
            if kb_id not in self._active_kbs:
                return True  # Already unloaded
            
            # Cleanup integrator
            try:
                await self._active_kbs[kb_id].cleanup()
            except Exception as e:
                logger.warning(f"Error during KB cleanup: {e}")
            
            # Remove from active KBs
            del self._active_kbs[kb_id]
            
            logger.info(f"Knowledge base '{kb_id}' unloaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unload knowledge base '{kb_id}': {e}")
            return False
    
    async def get_integrator(self, kb_id: str) -> RAGIntegrator:
        """Get RAG integrator for knowledge base (load if necessary).
        
        Args:
            kb_id: Knowledge base identifier
            
        Returns:
            RAG integrator instance
        """
        if kb_id in self._active_kbs:
            return self._active_kbs[kb_id]
        
        return await self.load_knowledge_base(kb_id)
    
    async def _calculate_kb_statistics(self, kb_dir: Path) -> Dict[str, Any]:
        """Calculate storage and content statistics for knowledge base.
        
        Args:
            kb_dir: Knowledge base directory
            
        Returns:
            Statistics dictionary
        """
        try:
            total_size = 0
            file_count = 0
            document_count = 0
            
            # Calculate total size and file count
            for file_path in kb_dir.rglob('*'):
                if file_path.is_file():
                    file_count += 1
                    total_size += file_path.stat().st_size
                    
                    # Count documents (simple heuristic)
                    if file_path.suffix.lower() in ['.json', '.txt', '.md']:
                        document_count += 1
            
            return {
                "document_count": document_count,
                "file_count": file_count,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "calculated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.warning(f"Failed to calculate KB statistics: {e}")
            return {
                "document_count": 0,
                "file_count": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
                "calculated_at": datetime.utcnow().isoformat(),
                "error": str(e)
            }
    
    async def cleanup(self) -> None:
        """Cleanup all active knowledge bases."""
        try:
            for kb_id, integrator in self._active_kbs.items():
                try:
                    await integrator.cleanup()
                    logger.info(f"Knowledge base '{kb_id}' cleaned up")
                except Exception as e:
                    logger.warning(f"Error cleaning up KB '{kb_id}': {e}")
            
            self._active_kbs.clear()
            logger.info("Knowledge base service cleanup completed")
            
        except Exception as e:
            logger.error(f"Knowledge base service cleanup failed: {e}")


# Global service instance
kb_service: Optional[KnowledgeBaseService] = None


def get_kb_service() -> KnowledgeBaseService:
    """Get global KB service instance."""
    global kb_service
    if kb_service is None:
        kb_service = KnowledgeBaseService()
    return kb_service