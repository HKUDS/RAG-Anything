"""Test configuration and fixtures."""

import asyncio
import os
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, AsyncGenerator
import pytest
import redis
from fastapi.testclient import TestClient

# Import test dependencies
from app.main import app
from app.services.auth_service import AuthService
from app.services.file_service import FileService
from app.services.rag_service import RAGService
from app.services.kb_service import KnowledgeBaseService
from app.config import settings


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
async def redis_client():
    """Create Redis client for tests."""
    # Use test database
    client = redis.Redis(
        host='localhost',
        port=6379,
        db=15,  # Test database
        decode_responses=True
    )
    
    try:
        # Test connection
        client.ping()
        yield client
    except redis.ConnectionError:
        # Mock Redis client for when Redis is not available
        from unittest.mock import AsyncMock, MagicMock
        
        mock_client = MagicMock()
        mock_client.ping = MagicMock(return_value=True)
        mock_client.get = AsyncMock(return_value=None)
        mock_client.set = AsyncMock(return_value=True)
        mock_client.setex = AsyncMock(return_value=True)
        mock_client.hset = AsyncMock(return_value=True)
        mock_client.hgetall = AsyncMock(return_value={})
        mock_client.delete = AsyncMock(return_value=True)
        mock_client.expire = AsyncMock(return_value=True)
        mock_client.keys = AsyncMock(return_value=[])
        mock_client.scan_iter = AsyncMock(return_value=iter([]))
        
        yield mock_client
    finally:
        if hasattr(client, 'flushdb'):
            try:
                client.flushdb()  # Clean test database
            except:
                pass


@pytest.fixture
async def auth_service(redis_client):
    """Create auth service for testing."""
    service = AuthService(redis_client)
    yield service


@pytest.fixture
async def file_service(temp_dir, redis_client):
    """Create file service for testing."""
    # Override settings for testing
    original_upload_dir = settings.files.upload_dir
    original_temp_dir = settings.files.temp_dir
    original_max_size = settings.files.max_file_size_mb
    
    settings.files.upload_dir = str(temp_dir / "uploads")
    settings.files.temp_dir = str(temp_dir / "temp")
    settings.files.max_file_size_mb = 10  # 10MB for tests
    
    service = FileService(redis_client=redis_client)
    yield service
    
    # Restore original settings
    settings.files.upload_dir = original_upload_dir
    settings.files.temp_dir = original_temp_dir
    settings.files.max_file_size_mb = original_max_size


@pytest.fixture
async def rag_service(temp_dir):
    """Create RAG service for testing."""
    config = {
        'working_dir': str(temp_dir / "rag_storage"),
        'lightrag_dir': str(temp_dir / "lightrag_storage"),
        'chunk_size': 500,
        'chunk_overlap': 50
    }
    
    service = RAGService(config=config)
    try:
        await service.initialize()
        yield service
    finally:
        await service.cleanup()


@pytest.fixture
async def kb_service(temp_dir):
    """Create KB service for testing."""
    service = KnowledgeBaseService(str(temp_dir / "kb_storage"))
    yield service
    await service.cleanup()


@pytest.fixture
def client():
    """Create test client."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def auth_headers(auth_service):
    """Create authentication headers for tests."""
    token = auth_service.create_access_token("test_user_123")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def api_key_headers(auth_service):
    """Create API key headers for tests."""
    api_key, _ = await auth_service.generate_api_key("test_user_123", "test-key")
    return {"X-API-Key": api_key}


@pytest.fixture
def sample_text_file():
    """Create sample text file for testing."""
    content = b"This is a test document for RAG-Anything API testing.\n\nIt contains multiple lines of text."
    return {
        "filename": "test.txt",
        "content": content,
        "mime_type": "text/plain"
    }


@pytest.fixture
def sample_pdf_content():
    """Create sample PDF-like content for testing."""
    # Minimal PDF structure for testing
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT
/F1 12 Tf
100 700 Td
(Test PDF content) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000015 00000 n 
0000000067 00000 n 
0000000124 00000 n 
0000000184 00000 n 
trailer
<< /Size 5 /Root 1 0 R >>
startxref
279
%%EOF"""
    
    return {
        "filename": "test.pdf",
        "content": pdf_content,
        "mime_type": "application/pdf"
    }


@pytest.fixture
def mock_upload_file():
    """Create mock UploadFile for testing."""
    from fastapi import UploadFile
    from io import BytesIO
    
    def create_upload_file(filename: str, content: bytes, content_type: str = "text/plain"):
        file_obj = BytesIO(content)
        upload_file = UploadFile(
            filename=filename,
            file=file_obj,
            size=len(content),
            headers={"content-type": content_type}
        )
        return upload_file
    
    return create_upload_file


# Test database configuration
@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment."""
    # Override settings for testing
    os.environ["TESTING"] = "1"
    os.environ["REDIS_URL"] = "redis://localhost:6379/15"
    
    yield
    
    # Cleanup
    if "TESTING" in os.environ:
        del os.environ["TESTING"]


# Async context manager for database transactions
@pytest.fixture
async def db_transaction():
    """Database transaction fixture for tests."""
    # This would be used with actual database connections
    # For now, it's a placeholder
    yield


# Mock external services
@pytest.fixture
def mock_openai():
    """Mock OpenAI API for testing."""
    from unittest.mock import patch, MagicMock
    
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Mocked LLM response for testing"
    
    with patch('openai.ChatCompletion.create', return_value=mock_response) as mock:
        yield mock


@pytest.fixture
def mock_embedding_service():
    """Mock embedding service for testing."""
    from unittest.mock import MagicMock
    import numpy as np
    
    mock_service = MagicMock()
    mock_service.embed_text.return_value = np.random.rand(384).tolist()  # Mock embedding
    mock_service.embed_batch.return_value = [np.random.rand(384).tolist() for _ in range(10)]
    
    return mock_service


# Performance testing fixtures
@pytest.fixture
def performance_timer():
    """Timer fixture for performance tests."""
    import time
    
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        def start(self):
            self.start_time = time.time()
        
        def stop(self):
            self.end_time = time.time()
        
        @property
        def elapsed(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None
    
    return Timer()


# Integration test data
@pytest.fixture
def integration_test_data():
    """Test data for integration tests."""
    return {
        "queries": [
            "What is the main topic of this document?",
            "Summarize the key points",
            "What are the recommendations?",
        ],
        "multimodal_content": [
            {
                "type": "table",
                "table_data": "Name,Age,City\nJohn,25,NYC\nJane,30,LA",
                "table_caption": "User data table"
            }
        ],
        "knowledge_bases": [
            {
                "kb_id": "test_kb_1",
                "name": "Test Knowledge Base 1",
                "description": "Test KB for integration testing"
            },
            {
                "kb_id": "test_kb_2",
                "name": "Test Knowledge Base 2",
                "description": "Another test KB"
            }
        ]
    }


# Security testing fixtures
@pytest.fixture
def malicious_file_content():
    """Malicious file content for security testing."""
    return {
        "script_injection": b"<script>alert('xss')</script>",
        "php_code": b"<?php system($_GET['cmd']); ?>",
        "executable": b"\x4d\x5a",  # PE executable header
        "large_file": b"A" * (100 * 1024 * 1024 + 1)  # > 100MB
    }


@pytest.fixture
async def concurrent_test_users():
    """Create multiple test users for concurrent testing."""
    users = []
    for i in range(10):
        users.append({
            "user_id": f"test_user_{i}",
            "token": f"test_token_{i}",
            "headers": {"Authorization": f"Bearer test_token_{i}"}
        })
    return users


# Enhanced fixtures for comprehensive testing
@pytest.fixture
def test_reporter():
    """Test reporter for metrics collection."""
    from tests.utils.reporting import TestReporter
    return TestReporter()


@pytest.fixture  
def performance_monitor():
    """Performance monitoring fixture."""
    from tests.utils.helpers import MemoryMonitor, TestTimer
    
    class PerformanceMonitor:
        def __init__(self):
            self.memory_monitor = MemoryMonitor()
            self.timer = TestTimer()
        
        def start_monitoring(self):
            self.memory_monitor.__enter__()
            self.timer.__enter__()
            return self
        
        def stop_monitoring(self):
            self.timer.__exit__(None, None, None)
            self.memory_monitor.__exit__(None, None, None)
            return {
                'duration': self.timer.elapsed,
                'memory_increase_mb': self.memory_monitor.memory_increase_mb,
                'peak_memory_mb': self.memory_monitor.peak_memory_mb
            }
    
    return PerformanceMonitor()


@pytest.fixture
def mock_service_manager():
    """Mock service manager for testing."""
    from tests.utils.helpers import MockServiceManager
    
    manager = MockServiceManager()
    yield manager
    manager.cleanup()


@pytest.fixture
def security_payloads():
    """Security test payloads."""
    from tests.utils.factories import MaliciousDataFactory
    
    return {
        'sql_injection': MaliciousDataFactory.create_sql_injection_payloads(),
        'xss': MaliciousDataFactory.create_xss_payloads(),
        'path_traversal': MaliciousDataFactory.create_path_traversal_payloads(),
        'command_injection': MaliciousDataFactory.create_command_injection_payloads(),
        'malicious_files': MaliciousDataFactory.create_malicious_files(),
    }


@pytest.fixture
def test_data_factory():
    """Test data factory for generating test data."""
    from tests.utils import factories
    
    class TestDataFactory:
        user = factories.UserFactory
        file = factories.FileFactory
        document = factories.DocumentFactory
        query = factories.QueryFactory
        kb = factories.KnowledgeBaseFactory
        response = factories.ResponseFactory
        performance = factories.PerformanceDataFactory
        malicious = factories.MaliciousDataFactory
    
    return TestDataFactory()


@pytest.fixture(scope='session')
def load_test_config():
    """Load test configuration."""
    return {
        'concurrent_users': {
            'light': 10,
            'medium': 50,
            'heavy': 200
        },
        'test_duration': {
            'short': '1m',
            'medium': '5m',
            'long': '30m'
        },
        'response_time_thresholds': {
            'health': 0.1,    # 100ms
            'auth': 0.5,      # 500ms
            'query': 2.0,     # 2s
            'upload': 10.0    # 10s
        },
        'memory_thresholds': {
            'per_request': 50,    # 50MB
            'peak_usage': 500,    # 500MB
            'leak_detection': 10  # 10MB increase per 100 requests
        }
    }


@pytest.fixture
def database_fixtures():
    """Database fixtures for testing."""
    
    class DatabaseFixtures:
        @staticmethod
        async def create_test_user(redis_client, user_data=None):
            """Create a test user in database."""
            from tests.utils.factories import UserFactory
            user = user_data or UserFactory.create_user()
            
            # Store in Redis (simulating database)
            user_key = f"user:{user['user_id']}"
            await redis_client.hset(user_key, mapping={
                'username': user['username'],
                'email': user['email'],
                'created_at': user['created_at'].isoformat(),
                'is_active': str(user['is_active']),
            })
            
            return user
        
        @staticmethod
        async def create_test_api_key(redis_client, user_id, key_data=None):
            """Create a test API key."""
            from tests.utils.factories import APIKeyFactory
            key = key_data or APIKeyFactory.create_api_key(user_id)
            
            key_id = f"api_key:{key['key_id']}"
            await redis_client.hset(key_id, mapping={
                'user_id': key['user_id'],
                'name': key['name'],
                'created_at': key['created_at'].isoformat(),
                'is_active': str(key['is_active']),
                'rate_limit_per_minute': str(key['rate_limit_per_minute']),
            })
            
            return key
        
        @staticmethod
        async def cleanup_test_data(redis_client, pattern='test_*'):
            """Clean up test data."""
            try:
                keys = await redis_client.keys(pattern)
                if keys:
                    await redis_client.delete(*keys)
            except Exception:
                pass  # Ignore cleanup errors
    
    return DatabaseFixtures()


@pytest.fixture
async def production_like_environment(redis_client, temp_dir):
    """Create production-like test environment."""
    
    class ProductionEnvironment:
        def __init__(self, redis_client, base_dir):
            self.redis_client = redis_client
            self.base_dir = base_dir
            self.services = {}
        
        async def setup_services(self):
            """Setup production-like services."""
            # Setup file service with production-like config
            from app.services.file_service import FileService
            
            self.services['file_service'] = FileService(
                redis_client=self.redis_client,
                upload_dir=str(self.base_dir / "uploads"),
                temp_dir=str(self.base_dir / "temp"),
                max_file_size_mb=100
            )
            
            # Setup RAG service with production config
            from app.services.rag_service import RAGService
            
            rag_config = {
                'working_dir': str(self.base_dir / "rag_storage"),
                'lightrag_dir': str(self.base_dir / "lightrag_storage"),
                'chunk_size': 1000,
                'chunk_overlap': 200,
                'enable_image_processing': True
            }
            
            self.services['rag_service'] = RAGService(config=rag_config)
            await self.services['rag_service'].initialize()
            
            return self.services
        
        async def cleanup_services(self):
            """Cleanup all services."""
            for service_name, service in self.services.items():
                if hasattr(service, 'cleanup'):
                    try:
                        await service.cleanup()
                    except Exception as e:
                        print(f"Error cleaning up {service_name}: {e}")
    
    env = ProductionEnvironment(redis_client, temp_dir)
    yield env
    await env.cleanup_services()


@pytest.fixture
def stress_test_data():
    """Generate data for stress testing."""
    from tests.utils.factories import FileFactory, QueryFactory
    
    return {
        'large_files': [
            FileFactory.create_large_file(size_mb=size)
            for size in [1, 5, 10, 25, 50]
        ],
        'many_queries': QueryFactory.create_batch_queries(100, 'text'),
        'multimodal_queries': QueryFactory.create_batch_queries(20, 'multimodal'),
        'concurrent_uploads': [
            FileFactory.create_text_file() for _ in range(50)
        ]
    }


@pytest.fixture(scope='session')
def benchmark_baseline():
    """Load benchmark baseline for comparison."""
    baseline_file = Path("benchmark_baseline.json")
    
    if baseline_file.exists():
        with open(baseline_file) as f:
            return json.load(f)
    else:
        # Return default baseline
        return {
            'auth_token_creation': {'mean': 0.001, 'stddev': 0.0001},
            'simple_query': {'mean': 0.1, 'stddev': 0.01},
            'file_upload_1mb': {'mean': 0.5, 'stddev': 0.05},
            'health_check': {'mean': 0.001, 'stddev': 0.0001},
        }


@pytest.fixture
async def isolated_test_environment():
    """Create isolated test environment for sensitive tests."""
    import tempfile
    import shutil
    from pathlib import Path
    
    # Create isolated temp directory
    isolated_dir = Path(tempfile.mkdtemp(prefix='isolated_test_'))
    
    # Create isolated Redis namespace (in practice, use separate Redis instance)
    test_namespace = f"isolated_test_{int(time.time())}"
    
    try:
        yield {
            'temp_dir': isolated_dir,
            'namespace': test_namespace,
            'redis_prefix': f"{test_namespace}:",
        }
    finally:
        # Cleanup
        shutil.rmtree(isolated_dir, ignore_errors=True)


@pytest.fixture
def hypothesis_strategies():
    """Hypothesis strategies for property-based testing."""
    try:
        from hypothesis import strategies as st
        
        return {
            'user_ids': st.text(min_size=1, max_size=50).filter(lambda x: x.isalnum()),
            'filenames': st.text(min_size=1, max_size=255).filter(
                lambda x: not any(char in x for char in '<>:"|?*')
            ),
            'query_text': st.text(min_size=1, max_size=10000),
            'file_content': st.binary(min_size=0, max_size=1024*1024),  # Up to 1MB
            'http_methods': st.sampled_from(['GET', 'POST', 'PUT', 'DELETE']),
            'status_codes': st.integers(min_value=200, max_value=599),
            'positive_integers': st.integers(min_value=1, max_value=10000),
        }
        
    except ImportError:
        return None  # Hypothesis not available


@pytest.fixture
async def chaos_testing_config():
    """Configuration for chaos testing."""
    return {
        'failure_modes': {
            'redis_connection_failure': {
                'probability': 0.1,
                'duration_seconds': 5,
                'recovery_time': 2
            },
            'rag_service_timeout': {
                'probability': 0.05,
                'duration_seconds': 30,
                'recovery_time': 1
            },
            'file_system_full': {
                'probability': 0.02,
                'simulation': 'permission_denied',
                'recovery_time': 3
            },
            'network_partition': {
                'probability': 0.03,
                'duration_seconds': 10,
                'recovery_time': 1
            }
        },
        'recovery_strategies': {
            'retry_with_backoff': {'max_retries': 3, 'backoff_factor': 2},
            'circuit_breaker': {'failure_threshold': 5, 'recovery_timeout': 60},
            'graceful_degradation': {'fallback_responses': True}
        }
    }


@pytest.fixture
def regression_test_cases():
    """Test cases for regression testing."""
    return [
        {
            'name': 'file_upload_edge_case_bug_123',
            'description': 'File upload with special characters in filename',
            'test_data': {
                'filename': 'test file (copy) [1].txt',
                'content': b'Test content with unicode: \xe2\x9c\x93',
            },
            'expected_status': 200,
            'bug_report': 'https://github.com/issues/123'
        },
        {
            'name': 'query_timeout_bug_456',
            'description': 'Long query causing timeout',
            'test_data': {
                'query': 'What is ' + 'very ' * 1000 + 'important?',
                'mode': 'hybrid'
            },
            'expected_status': 422,  # Should be rejected due to length
            'bug_report': 'https://github.com/issues/456'
        }
    ]


# Async fixtures for advanced testing
@pytest.fixture(scope='session')
async def persistent_test_session():
    """Session-level async fixture for persistent test setup."""
    
    class TestSession:
        def __init__(self):
            self.session_id = f"test_session_{int(time.time())}"
            self.shared_data = {}
            self.cleanup_tasks = []
        
        def add_cleanup_task(self, coro):
            """Add cleanup task to run at session end."""
            self.cleanup_tasks.append(coro)
        
        async def cleanup(self):
            """Run all cleanup tasks."""
            for task in self.cleanup_tasks:
                try:
                    await task
                except Exception as e:
                    print(f"Cleanup task failed: {e}")
    
    session = TestSession()
    
    try:
        yield session
    finally:
        await session.cleanup()


# API testing fixtures
@pytest.fixture
def api_test_client_factory():
    """Factory for creating API test clients with different configurations."""
    
    def create_client(config=None):
        """Create test client with specific configuration."""
        from fastapi.testclient import TestClient
        from app.main import app
        
        # Apply configuration overrides if provided
        if config:
            # In a real implementation, you'd override app configuration here
            pass
        
        return TestClient(app)
    
    return create_client


@pytest.fixture
async def websocket_test_client():
    """WebSocket test client for real-time features."""
    try:
        from fastapi.testclient import TestClient
        from app.main import app
        
        with TestClient(app) as client:
            # Create WebSocket connection
            # Note: This would need actual WebSocket endpoints in the app
            yield client
    
    except Exception:
        # WebSocket testing not available
        yield None