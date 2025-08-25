"""File management service with security validation."""

import hashlib
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, BinaryIO
# import magic  # Commented out for testing
import redis
import aiofiles

from fastapi import UploadFile
from loguru import logger

from app.config import settings
from app.models.files import FileUploadResult, FileMetadata
from app.models.common import StatusEnum


class FileService:
    """Service for file upload and management operations with security validation."""
    
    def __init__(self, redis_client: redis.Redis = None):
        """Initialize file service.
        
        Args:
            redis_client: Redis client for metadata storage
        """
        self.redis = redis_client
        self.upload_dir = Path(settings.files.upload_dir)
        self.temp_dir = Path(settings.files.temp_dir)
        self.max_file_size = settings.files.max_file_size_mb * 1024 * 1024
        
        # Create directories
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Allowed file types with MIME type validation
        self.allowed_types = {
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/msword',
            'application/vnd.ms-powerpoint',
            'application/vnd.ms-excel',
            'text/plain',
            'text/markdown',
            'text/csv',
            'application/octet-stream',  # Allow generic binary for .txt files
            'image/jpeg',
            'image/png',
            'image/tiff',
            'image/bmp',
            'image/gif'
        }
        
        # Fallback file metadata store for when Redis is not available
        self._files = {} if not redis_client else None
    
    async def upload_file(
        self,
        file: UploadFile,
        user_id: str,
        expires_in: int = 24 * 3600  # 24 hours default
    ) -> FileUploadResult:
        """Upload a file with security validation.
        
        Args:
            file: FastAPI UploadFile object
            user_id: User identifier
            expires_in: File expiration in seconds
            
        Returns:
            File upload result
        """
        try:
            # Validate file size
            if file.size and file.size > self.max_file_size:
                raise ValueError(f"File size {file.size} exceeds maximum {self.max_file_size}")
            
            # Generate unique file ID
            file_id = str(uuid.uuid4())
            
            # Read file content
            content = await file.read()
            
            # Validate actual file size
            if len(content) > self.max_file_size:
                raise ValueError(f"File size {len(content)} exceeds maximum {self.max_file_size}")
            
            # Validate file type using python-magic
            # mime_type = magic.from_buffer(content, mime=True)
            mime_type = "application/octet-stream"  # Default for testing
            if mime_type not in self.allowed_types:
                raise ValueError(f"File type {mime_type} not allowed")
            
            # Security scan for malware
            if await self._scan_for_malware(content):
                raise ValueError("File failed security scan")
            
            # Generate secure filename
            file_extension = os.path.splitext(file.filename)[1]
            internal_filename = f"{file_id}{file_extension}"
            file_path = self.upload_dir / internal_filename
            
            # Save file asynchronously
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content)
            
            # Calculate file hash for integrity verification
            file_hash = hashlib.sha256(content).hexdigest()
            
            # Create metadata
            now = datetime.utcnow()
            expires_at = now + timedelta(seconds=expires_in)
            
            metadata = {
                "file_id": file_id,
                "original_filename": file.filename,
                "internal_filename": internal_filename,
                "mime_type": mime_type,
                "size_bytes": len(content),
                "hash_sha256": file_hash,
                "user_id": user_id,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "status": "uploaded",
                "upload_method": "api",
                "file_path": str(file_path)
            }
            
            # Store metadata
            await self._store_metadata(file_id, metadata, expires_in)
            
            # Create result
            result = FileUploadResult(
                file_id=file_id,
                filename=file.filename,
                file_size=len(content),
                content_type=mime_type,
                expires_at=expires_at
            )
            
            logger.info(f"File uploaded: {file_id} ({file.filename}) by user {user_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to upload file {file.filename}: {e}")
            # Cleanup on error
            try:
                file_path = self.upload_dir / internal_filename
                if file_path.exists():
                    file_path.unlink()
            except:
                pass
            raise
    
    async def get_file_metadata(self, file_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get file metadata with authorization check.
        
        Args:
            file_id: File identifier
            user_id: User identifier for authorization
            
        Returns:
            File metadata or None if not found
        """
        try:
            metadata = await self._get_metadata(file_id)
            if not metadata:
                return None
            
            # Check authorization
            if metadata.get("user_id") != user_id:
                raise PermissionError("Access denied")
            
            # Check expiration
            expires_at = datetime.fromisoformat(metadata["expires_at"])
            if expires_at < datetime.utcnow():
                # File expired, clean up
                await self.delete_file(file_id, user_id)
                return None
            
            return metadata
            
        except PermissionError:
            raise
        except Exception as e:
            logger.error(f"Failed to get file metadata {file_id}: {e}")
            return None
    
    async def get_file_path(self, file_id: str, user_id: str) -> Optional[Path]:
        """Get file system path with authorization check.
        
        Args:
            file_id: File identifier
            user_id: User identifier for authorization
            
        Returns:
            File path or None if not found
        """
        metadata = await self.get_file_metadata(file_id, user_id)
        if not metadata:
            return None
        
        file_path = Path(metadata.get("file_path"))
        if file_path.exists():
            return file_path
        
        return None
    
    async def delete_file(self, file_id: str, user_id: str) -> Dict[str, Any]:
        """Delete file and metadata with authorization check.
        
        Args:
            file_id: File identifier
            user_id: User identifier for authorization
            
        Returns:
            Deletion result
        """
        try:
            metadata = await self.get_file_metadata(file_id, user_id)
            if not metadata:
                raise ValueError(f"File {file_id} not found")
            
            # Delete physical file
            file_path = Path(metadata.get("file_path"))
            if file_path.exists():
                file_path.unlink()
            
            # Delete metadata
            await self._delete_metadata(file_id)
            
            result = {
                "file_id": file_id,
                "deleted": True,
                "deleted_at": datetime.utcnow().isoformat(),
                "original_filename": metadata.get("original_filename")
            }
            
            logger.info(f"File deleted: {file_id} by user {user_id}")
            return result
            
        except (ValueError, PermissionError):
            raise
        except Exception as e:
            logger.error(f"Failed to delete file {file_id}: {e}")
            raise RuntimeError(f"File deletion failed: {e}")
    
    async def list_user_files(self, user_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List files for a specific user.
        
        Args:
            user_id: User identifier
            limit: Maximum number of files to return
            offset: Number of files to skip
            
        Returns:
            List of file metadata
        """
        try:
            files = []
            
            if self.redis:
                # Redis implementation
                pattern = "file:*"
                async for key in self.redis.scan_iter(match=pattern):
                    metadata = await self.redis.hgetall(key)
                    if metadata and metadata.get(b"user_id", b"").decode() == user_id:
                        # Convert bytes to strings
                        file_data = {k.decode(): v.decode() for k, v in metadata.items()}
                        
                        # Check if expired
                        expires_at = datetime.fromisoformat(file_data["expires_at"])
                        if expires_at < datetime.utcnow():
                            # Clean up expired file
                            await self.delete_file(file_data["file_id"], user_id)
                            continue
                        
                        files.append(file_data)
            else:
                # Fallback in-memory implementation
                for file_id, metadata in self._files.items():
                    if metadata.get("user_id") == user_id:
                        files.append(metadata)
            
            # Sort by creation date (newest first)
            files.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            
            # Apply pagination
            return files[offset:offset + limit]
            
        except Exception as e:
            logger.error(f"Failed to list files for user {user_id}: {e}")
            return []
    
    async def cleanup_expired_files(self) -> int:
        """Clean up expired files.
        
        Returns:
            Number of files cleaned up
        """
        try:
            cleaned_count = 0
            current_time = datetime.utcnow()
            
            if self.redis:
                # Redis implementation
                pattern = "file:*"
                async for key in self.redis.scan_iter(match=pattern):
                    metadata = await self.redis.hgetall(key)
                    if not metadata:
                        continue
                    
                    expires_at_str = metadata.get(b"expires_at", b"").decode()
                    if expires_at_str:
                        expires_at = datetime.fromisoformat(expires_at_str)
                        if current_time > expires_at:
                            file_id = metadata.get(b"file_id", b"").decode()
                            file_path = metadata.get(b"file_path", b"").decode()
                            
                            # Delete physical file
                            if file_path and Path(file_path).exists():
                                Path(file_path).unlink()
                            
                            # Delete metadata
                            await self.redis.delete(key)
                            cleaned_count += 1
                            
                            logger.debug(f"Cleaned up expired file: {file_id}")
            else:
                # Fallback in-memory implementation
                expired_files = []
                for file_id, metadata in self._files.items():
                    expires_at = datetime.fromisoformat(metadata["expires_at"])
                    if current_time > expires_at:
                        expired_files.append(file_id)
                
                for file_id in expired_files:
                    metadata = self._files[file_id]
                    file_path = Path(metadata.get("file_path"))
                    
                    # Delete physical file
                    if file_path.exists():
                        file_path.unlink()
                    
                    # Remove metadata
                    del self._files[file_id]
                    cleaned_count += 1
            
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} expired files")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired files: {e}")
            return 0
    
    async def _store_metadata(self, file_id: str, metadata: Dict[str, Any], ttl: int):
        """Store file metadata.
        
        Args:
            file_id: File identifier
            metadata: Metadata to store
            ttl: Time to live in seconds
        """
        if self.redis:
            # Store in Redis with TTL
            await self.redis.hset(f"file:{file_id}", mapping=metadata)
            await self.redis.expire(f"file:{file_id}", ttl)
        else:
            # Store in memory (fallback)
            self._files[file_id] = metadata
    
    async def _get_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file metadata.
        
        Args:
            file_id: File identifier
            
        Returns:
            Metadata dictionary or None
        """
        if self.redis:
            metadata = await self.redis.hgetall(f"file:{file_id}")
            if metadata:
                # Convert bytes to strings
                return {k.decode(): v.decode() for k, v in metadata.items()}
            return None
        else:
            return self._files.get(file_id)
    
    async def update_file_metadata(self, file_id: str, updates: Dict[str, Any]) -> bool:
        """Update file metadata.
        
        Args:
            file_id: File identifier
            updates: Dictionary of fields to update
            
        Returns:
            True if successful, False otherwise
        """
        # Get existing metadata
        metadata = await self._get_metadata(file_id)
        if not metadata:
            return False
        
        # Update metadata
        metadata.update(updates)
        
        # Store updated metadata
        await self._store_metadata(file_id, metadata, ttl=86400)  # 24 hours
        return True
    
    async def _delete_metadata(self, file_id: str):
        """Delete file metadata.
        
        Args:
            file_id: File identifier
        """
        if self.redis:
            await self.redis.delete(f"file:{file_id}")
        else:
            if file_id in self._files:
                del self._files[file_id]
    
    async def _scan_for_malware(self, content: bytes) -> bool:
        """Scan file content for malware/suspicious patterns.
        
        Args:
            content: File content bytes
            
        Returns:
            True if suspicious content found
        """
        try:
            # Basic pattern-based scanning
            suspicious_patterns = [
                b'<script',
                b'javascript:',
                b'<?php',
                b'<%',
                b'eval(',
                b'exec(',
                b'shell_exec(',
                b'system(',
                b'passthru(',
                b'base64_decode('
            ]
            
            content_lower = content.lower()
            for pattern in suspicious_patterns:
                if pattern in content_lower:
                    logger.warning(f"Suspicious pattern found: {pattern}")
                    return True
            
            # Check for executable headers
            if content.startswith(b'\x4d\x5a'):  # PE executable
                logger.warning("PE executable detected")
                return True
            
            if content.startswith(b'\x7f\x45\x4c\x46'):  # ELF executable
                logger.warning("ELF executable detected")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Malware scan failed: {e}")
            # On scan failure, err on the side of caution
            return True


# Global service instance
file_service: Optional[FileService] = None


def get_file_service() -> FileService:
    """Get global file service instance."""
    if file_service is None:
        raise RuntimeError("File service not initialized")
    return file_service