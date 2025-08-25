"""Test helper functions and utilities."""

import asyncio
import json
import time
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Any, Callable, Optional, Union
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import psutil
from fastapi.testclient import TestClient


class TestTimer:
    """Context manager for timing test operations."""
    
    def __init__(self):
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.elapsed: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.elapsed = self.end_time - self.start_time
    
    def assert_under(self, max_seconds: float):
        """Assert that elapsed time is under the given threshold."""
        assert self.elapsed is not None, "Timer not completed"
        assert self.elapsed < max_seconds, f"Operation took {self.elapsed:.2f}s, expected under {max_seconds}s"
    
    def assert_over(self, min_seconds: float):
        """Assert that elapsed time is over the given threshold."""
        assert self.elapsed is not None, "Timer not completed"
        assert self.elapsed > min_seconds, f"Operation took {self.elapsed:.2f}s, expected over {min_seconds}s"


class MemoryMonitor:
    """Monitor memory usage during tests."""
    
    def __init__(self):
        self.process = psutil.Process()
        self.initial_memory: Optional[int] = None
        self.peak_memory: Optional[int] = None
        self.final_memory: Optional[int] = None
    
    def __enter__(self):
        self.initial_memory = self.process.memory_info().rss
        self.peak_memory = self.initial_memory
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.final_memory = self.process.memory_info().rss
        self.peak_memory = max(self.peak_memory or 0, self.final_memory)
    
    def update_peak(self):
        """Update peak memory usage."""
        current_memory = self.process.memory_info().rss
        self.peak_memory = max(self.peak_memory or 0, current_memory)
    
    @property
    def memory_increase_mb(self) -> float:
        """Get memory increase in MB."""
        if self.initial_memory and self.final_memory:
            return (self.final_memory - self.initial_memory) / 1024 / 1024
        return 0
    
    @property
    def peak_memory_mb(self) -> float:
        """Get peak memory usage in MB."""
        return (self.peak_memory or 0) / 1024 / 1024
    
    def assert_memory_increase_under(self, max_mb: float):
        """Assert memory increase is under threshold."""
        increase = self.memory_increase_mb
        assert increase < max_mb, f"Memory increased by {increase:.1f}MB, expected under {max_mb}MB"


class ConcurrencyTester:
    """Helper for testing concurrent operations."""
    
    @staticmethod
    async def run_concurrent_tasks(tasks: List[Callable], max_concurrent: int = 10) -> List[Any]:
        """Run tasks concurrently with controlled concurrency."""
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def run_with_semaphore(task):
            async with semaphore:
                return await task() if asyncio.iscoroutinefunction(task) else task()
        
        return await asyncio.gather(*[run_with_semaphore(task) for task in tasks])
    
    @staticmethod
    async def stress_test_endpoint(
        client: TestClient, 
        endpoint: str, 
        method: str = 'GET',
        headers: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        concurrent_requests: int = 50,
        total_requests: int = 200
    ) -> Dict[str, Any]:
        """Stress test an endpoint with concurrent requests."""
        results = {
            'successful': 0,
            'failed': 0,
            'status_codes': {},
            'response_times': [],
            'errors': []
        }
        
        async def make_request():
            start_time = time.time()
            try:
                if method.upper() == 'GET':
                    response = client.get(endpoint, headers=headers)
                elif method.upper() == 'POST':
                    response = client.post(endpoint, headers=headers, json=json_data)
                else:
                    response = client.request(method, endpoint, headers=headers, json=json_data)
                
                response_time = time.time() - start_time
                
                status_code = response.status_code
                results['status_codes'][status_code] = results['status_codes'].get(status_code, 0) + 1
                results['response_times'].append(response_time)
                
                if 200 <= status_code < 300:
                    results['successful'] += 1
                else:
                    results['failed'] += 1
                
                return response
                
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(str(e))
                return None
        
        # Run requests in batches to control concurrency
        for batch_start in range(0, total_requests, concurrent_requests):
            batch_size = min(concurrent_requests, total_requests - batch_start)
            tasks = [make_request for _ in range(batch_size)]
            await ConcurrencyTester.run_concurrent_tasks(tasks, concurrent_requests)
        
        # Calculate statistics
        if results['response_times']:
            results['avg_response_time'] = sum(results['response_times']) / len(results['response_times'])
            results['max_response_time'] = max(results['response_times'])
            results['min_response_time'] = min(results['response_times'])
        
        results['success_rate'] = results['successful'] / total_requests if total_requests > 0 else 0
        
        return results


class MockServiceManager:
    """Manager for creating and controlling mock services."""
    
    def __init__(self):
        self.active_patches = []
    
    def mock_rag_service(self, responses: Optional[Dict[str, Any]] = None):
        """Mock RAG service with predefined responses."""
        default_responses = {
            'query': {
                'response': 'Mocked RAG response',
                'sources': [{'document_id': 'mock_doc_1', 'score': 0.95}],
                'metadata': {'query_time': 0.1, 'mode': 'hybrid'}
            },
            'process_document': {
                'status': 'success',
                'document_id': 'mock_doc_123',
                'chunks_created': 5
            }
        }
        
        responses = responses or default_responses
        
        mock_rag = MagicMock()
        for method, response in responses.items():
            if asyncio.iscoroutinefunction(response):
                setattr(mock_rag, method, AsyncMock(return_value=response))
            else:
                setattr(mock_rag, method, AsyncMock(return_value=response))
        
        patch_obj = patch('app.services.rag_service.rag_service', mock_rag)
        self.active_patches.append(patch_obj)
        return patch_obj.start()
    
    def mock_redis_client(self, failure_mode: Optional[str] = None):
        """Mock Redis client with optional failure modes."""
        mock_redis = AsyncMock()
        
        if failure_mode == 'connection_error':
            mock_redis.ping.side_effect = Exception("Redis connection failed")
            mock_redis.get.side_effect = Exception("Redis connection failed")
            mock_redis.set.side_effect = Exception("Redis connection failed")
        elif failure_mode == 'timeout':
            mock_redis.ping.side_effect = Exception("Redis operation timed out")
            mock_redis.get.side_effect = Exception("Redis operation timed out")
        elif failure_mode == 'intermittent':
            call_count = 0
            def intermittent_failure(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count % 3 == 0:
                    raise Exception("Intermittent Redis failure")
                return AsyncMock(return_value=True)()
            
            mock_redis.get = intermittent_failure
            mock_redis.set = intermittent_failure
        else:
            # Normal operation
            mock_redis.ping.return_value = True
            mock_redis.get.return_value = None
            mock_redis.set.return_value = True
            mock_redis.setex.return_value = True
            mock_redis.hset.return_value = True
            mock_redis.hgetall.return_value = {}
            mock_redis.delete.return_value = True
        
        patch_obj = patch('redis.Redis', return_value=mock_redis)
        self.active_patches.append(patch_obj)
        return patch_obj.start()
    
    def mock_file_service(self, responses: Optional[Dict[str, Any]] = None):
        """Mock file service operations."""
        default_responses = {
            'upload_file': {
                'file_id': 'mock_file_123',
                'filename': 'mock_file.txt',
                'size': 1024,
                'content_type': 'text/plain'
            },
            'get_file_info': {
                'file_id': 'mock_file_123',
                'filename': 'mock_file.txt',
                'size': 1024,
                'content_type': 'text/plain',
                'created_at': '2024-01-01T00:00:00Z'
            }
        }
        
        responses = responses or default_responses
        
        mock_service = MagicMock()
        for method, response in responses.items():
            setattr(mock_service, method, AsyncMock(return_value=response))
        
        patch_obj = patch('app.services.file_service.file_service', mock_service)
        self.active_patches.append(patch_obj)
        return patch_obj.start()
    
    def cleanup(self):
        """Stop all active patches."""
        for patch_obj in self.active_patches:
            try:
                patch_obj.stop()
            except:
                pass
        self.active_patches.clear()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


class APIResponseValidator:
    """Validator for API responses."""
    
    @staticmethod
    def validate_success_response(response_data: Dict[str, Any], expected_fields: Optional[List[str]] = None):
        """Validate a successful API response structure."""
        assert 'success' in response_data or response_data.get('success') is not False
        
        if expected_fields:
            for field in expected_fields:
                assert field in response_data, f"Expected field '{field}' not found in response"
    
    @staticmethod
    def validate_error_response(response_data: Dict[str, Any], expected_error_code: Optional[str] = None):
        """Validate an error API response structure."""
        assert 'error' in response_data or 'detail' in response_data
        
        if expected_error_code:
            error_code = response_data.get('error') or response_data.get('detail')
            assert expected_error_code in str(error_code).upper()
    
    @staticmethod
    def validate_pagination_response(response_data: Dict[str, Any]):
        """Validate a paginated API response."""
        assert 'data' in response_data
        assert 'pagination' in response_data
        
        pagination = response_data['pagination']
        required_fields = ['page', 'per_page', 'total_items', 'total_pages', 'has_next', 'has_prev']
        
        for field in required_fields:
            assert field in pagination, f"Missing pagination field: {field}"
        
        # Validate pagination logic
        assert pagination['page'] > 0
        assert pagination['per_page'] > 0
        assert pagination['total_items'] >= 0
        assert pagination['total_pages'] >= 0
    
    @staticmethod
    def validate_streaming_response(response):
        """Validate a streaming API response."""
        assert response.headers.get('content-type') in [
            'text/event-stream',
            'application/x-ndjson',
            'application/json'
        ]
        
        # Basic check for streaming content
        if hasattr(response, 'iter_content'):
            chunks_received = 0
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    chunks_received += 1
                    if chunks_received > 5:  # Prevent infinite loops in tests
                        break
            
            assert chunks_received > 0, "No streaming content received"


class FileTestHelper:
    """Helper for file-related tests."""
    
    @staticmethod
    @contextmanager
    def temporary_file(content: bytes, filename: str = "test_file.txt"):
        """Create a temporary file for testing."""
        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            
            try:
                yield Path(temp_file.name)
            finally:
                Path(temp_file.name).unlink(missing_ok=True)
    
    @staticmethod
    @contextmanager
    def temporary_directory():
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        try:
            yield Path(temp_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @staticmethod
    def create_test_files_in_directory(directory: Path, file_specs: List[Dict[str, Any]]):
        """Create multiple test files in a directory."""
        created_files = []
        
        for spec in file_specs:
            filename = spec['filename']
            content = spec['content']
            
            file_path = directory / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            if isinstance(content, str):
                file_path.write_text(content, encoding='utf-8')
            else:
                file_path.write_bytes(content)
            
            created_files.append(file_path)
        
        return created_files


class DatabaseTestHelper:
    """Helper for database-related tests."""
    
    @staticmethod
    async def wait_for_redis_ready(redis_client, timeout: float = 10.0):
        """Wait for Redis to be ready."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                await redis_client.ping()
                return True
            except Exception:
                await asyncio.sleep(0.1)
        
        return False
    
    @staticmethod
    async def clean_redis_test_data(redis_client, pattern: str = "test_*"):
        """Clean up Redis test data."""
        try:
            keys = await redis_client.keys(pattern)
            if keys:
                await redis_client.delete(*keys)
        except Exception:
            pass  # Ignore cleanup errors
    
    @staticmethod
    @asynccontextmanager
    async def redis_transaction(redis_client):
        """Context manager for Redis transactions."""
        pipe = redis_client.pipeline()
        try:
            yield pipe
            await pipe.execute()
        except Exception:
            # Rollback would happen here in a real transaction system
            raise
        finally:
            try:
                await pipe.reset()
            except:
                pass


class SecurityTestHelper:
    """Helper for security-related tests."""
    
    @staticmethod
    def create_malicious_payload(attack_type: str) -> str:
        """Create malicious payload for security testing."""
        payloads = {
            'sql_injection': "'; DROP TABLE users; --",
            'xss': "<script>alert('xss')</script>",
            'path_traversal': "../../../etc/passwd",
            'command_injection': "; cat /etc/passwd",
            'ldap_injection': "*)(uid=*",
            'xxe': '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>',
        }
        
        return payloads.get(attack_type, "generic_malicious_payload")
    
    @staticmethod
    def validate_security_headers(response_headers: Dict[str, str]):
        """Validate security headers in response."""
        security_headers = {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': ['DENY', 'SAMEORIGIN'],
            'X-XSS-Protection': '1; mode=block',
        }
        
        for header, expected_values in security_headers.items():
            if header in response_headers:
                actual_value = response_headers[header]
                if isinstance(expected_values, list):
                    assert actual_value in expected_values, f"Invalid {header}: {actual_value}"
                else:
                    assert actual_value == expected_values, f"Invalid {header}: {actual_value}"
    
    @staticmethod
    def check_for_information_disclosure(response_text: str) -> List[str]:
        """Check response for potential information disclosure."""
        sensitive_patterns = [
            r'password',
            r'secret',
            r'key',
            r'token',
            r'internal',
            r'database',
            r'traceback',
            r'exception',
            r'/home/',
            r'/etc/',
            r'c:\\',
            r'stack trace'
        ]
        
        import re
        found_patterns = []
        
        for pattern in sensitive_patterns:
            if re.search(pattern, response_text, re.IGNORECASE):
                found_patterns.append(pattern)
        
        return found_patterns


class PerformanceTestHelper:
    """Helper for performance testing."""
    
    @staticmethod
    def measure_throughput(operation: Callable, duration_seconds: float = 10.0) -> Dict[str, Any]:
        """Measure operation throughput over time."""
        start_time = time.time()
        end_time = start_time + duration_seconds
        operation_count = 0
        errors = 0
        response_times = []
        
        while time.time() < end_time:
            op_start = time.time()
            try:
                operation()
                operation_count += 1
            except Exception:
                errors += 1
            
            op_end = time.time()
            response_times.append(op_end - op_start)
        
        total_time = time.time() - start_time
        
        return {
            'operations_per_second': operation_count / total_time,
            'total_operations': operation_count,
            'errors': errors,
            'error_rate': errors / (operation_count + errors) if (operation_count + errors) > 0 else 0,
            'avg_response_time': sum(response_times) / len(response_times) if response_times else 0,
            'max_response_time': max(response_times) if response_times else 0,
            'min_response_time': min(response_times) if response_times else 0,
        }
    
    @staticmethod
    def create_load_pattern(pattern_type: str, duration: int = 60) -> List[int]:
        """Create user load patterns for testing."""
        patterns = {
            'constant': [50] * duration,
            'ramp_up': list(range(1, duration + 1)),
            'spike': [10] * 20 + [100] * 10 + [10] * (duration - 30),
            'step': [10] * 15 + [25] * 15 + [50] * 15 + [25] * 15,
        }
        
        return patterns.get(pattern_type, [10] * duration)


# Convenience functions
def assert_response_time_under(response, max_seconds: float):
    """Assert that response time is under threshold."""
    if hasattr(response, 'elapsed'):
        elapsed = response.elapsed.total_seconds()
        assert elapsed < max_seconds, f"Response took {elapsed:.2f}s, expected under {max_seconds}s"


def assert_memory_usage_under(max_mb: float):
    """Assert that current memory usage is under threshold."""
    current_memory_mb = psutil.Process().memory_info().rss / 1024 / 1024
    assert current_memory_mb < max_mb, f"Memory usage {current_memory_mb:.1f}MB exceeds {max_mb}MB"


def skip_if_service_unavailable(service_name: str, check_func: Callable):
    """Skip test if external service is unavailable."""
    try:
        check_func()
        return lambda func: func  # Return function unchanged
    except Exception:
        return pytest.mark.skip(f"{service_name} service unavailable")


def retry_on_failure(max_retries: int = 3, delay: float = 0.1):
    """Decorator to retry test operations on failure."""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
            raise last_exception
        
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        time.sleep(delay)
            raise last_exception
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator