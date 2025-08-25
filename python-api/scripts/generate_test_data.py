#!/usr/bin/env python3
"""
Generate test data for RAG-Anything API testing.
Creates realistic test datasets for comprehensive testing.
"""

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List, Any

from tests.utils.factories import (
    UserFactory, FileFactory, DocumentFactory, 
    QueryFactory, KnowledgeBaseFactory, MaliciousDataFactory
)


def generate_users(count: int = 100) -> List[Dict[str, Any]]:
    """Generate test users."""
    return UserFactory.create_batch_users(count)


def generate_files(count: int = 50, mix_types: bool = True) -> List[Dict[str, Any]]:
    """Generate test files."""
    if mix_types:
        return FileFactory.create_batch_files(count, 'mixed')
    else:
        files = []
        # 60% text, 30% PDF, 10% images
        text_count = int(count * 0.6)
        pdf_count = int(count * 0.3) 
        image_count = count - text_count - pdf_count
        
        files.extend(FileFactory.create_batch_files(text_count, 'text'))
        files.extend(FileFactory.create_batch_files(pdf_count, 'pdf'))
        files.extend(FileFactory.create_batch_files(image_count, 'image'))
        
        return files


def generate_documents(count: int = 200) -> List[Dict[str, Any]]:
    """Generate test documents."""
    documents = []
    
    # 70% regular documents, 30% multimodal
    regular_count = int(count * 0.7)
    multimodal_count = count - regular_count
    
    for _ in range(regular_count):
        documents.append(DocumentFactory.create_document())
    
    for _ in range(multimodal_count):
        documents.append(DocumentFactory.create_multimodal_document())
    
    return documents


def generate_queries(count: int = 500) -> List[Dict[str, Any]]:
    """Generate test queries."""
    queries = []
    
    # 80% text queries, 20% multimodal
    text_count = int(count * 0.8)
    multimodal_count = count - text_count
    
    queries.extend(QueryFactory.create_batch_queries(text_count, 'text'))
    queries.extend(QueryFactory.create_batch_queries(multimodal_count, 'multimodal'))
    
    return queries


def generate_knowledge_bases(count: int = 20) -> List[Dict[str, Any]]:
    """Generate test knowledge bases."""
    return [KnowledgeBaseFactory.create_knowledge_base() for _ in range(count)]


def generate_security_payloads() -> Dict[str, List[str]]:
    """Generate security test payloads."""
    return {
        'sql_injection': MaliciousDataFactory.create_sql_injection_payloads(),
        'xss': MaliciousDataFactory.create_xss_payloads(),
        'path_traversal': MaliciousDataFactory.create_path_traversal_payloads(),
        'command_injection': MaliciousDataFactory.create_command_injection_payloads(),
    }


def generate_performance_scenarios() -> List[Dict[str, Any]]:
    """Generate performance testing scenarios."""
    scenarios = []
    
    # Light load scenario
    scenarios.append({
        'name': 'light_load',
        'description': 'Light load testing scenario',
        'users': 10,
        'spawn_rate': 1,
        'duration': '2m',
        'endpoints': [
            {'path': '/api/v1/health', 'weight': 5, 'method': 'GET'},
            {'path': '/api/v1/query', 'weight': 2, 'method': 'POST'},
        ]
    })
    
    # Medium load scenario
    scenarios.append({
        'name': 'medium_load',
        'description': 'Medium load testing scenario',
        'users': 50,
        'spawn_rate': 5,
        'duration': '5m',
        'endpoints': [
            {'path': '/api/v1/health', 'weight': 3, 'method': 'GET'},
            {'path': '/api/v1/query', 'weight': 4, 'method': 'POST'},
            {'path': '/api/v1/files/upload', 'weight': 2, 'method': 'POST'},
            {'path': '/api/v1/files', 'weight': 1, 'method': 'GET'},
        ]
    })
    
    # Heavy load scenario
    scenarios.append({
        'name': 'heavy_load',
        'description': 'Heavy load testing scenario',
        'users': 200,
        'spawn_rate': 10,
        'duration': '10m',
        'endpoints': [
            {'path': '/api/v1/health', 'weight': 2, 'method': 'GET'},
            {'path': '/api/v1/query', 'weight': 5, 'method': 'POST'},
            {'path': '/api/v1/files/upload', 'weight': 3, 'method': 'POST'},
            {'path': '/api/v1/files', 'weight': 2, 'method': 'GET'},
            {'path': '/api/v1/kb', 'weight': 1, 'method': 'GET'},
        ]
    })
    
    # Spike test scenario
    scenarios.append({
        'name': 'spike_test',
        'description': 'Spike testing scenario',
        'users': 500,
        'spawn_rate': 50,
        'duration': '3m',
        'endpoints': [
            {'path': '/api/v1/health', 'weight': 10, 'method': 'GET'},
        ]
    })
    
    return scenarios


def generate_regression_test_cases() -> List[Dict[str, Any]]:
    """Generate regression test cases."""
    return [
        {
            'id': 'REG-001',
            'name': 'file_upload_unicode_filename',
            'description': 'Test file upload with Unicode characters in filename',
            'category': 'file_handling',
            'test_data': {
                'filename': 'tëst_fîlé_with_ünïcödé.txt',
                'content': 'Test content with Unicode: 测试内容',
                'expected_status': 200
            },
            'bug_reference': 'https://github.com/issues/001'
        },
        {
            'id': 'REG-002', 
            'name': 'large_query_handling',
            'description': 'Test handling of very large queries',
            'category': 'query_processing',
            'test_data': {
                'query': 'What is ' + 'very ' * 2000 + 'important information?',
                'expected_status': 422
            },
            'bug_reference': 'https://github.com/issues/002'
        },
        {
            'id': 'REG-003',
            'name': 'concurrent_kb_access',
            'description': 'Test concurrent access to same knowledge base',
            'category': 'concurrency',
            'test_data': {
                'kb_id': 'shared_kb_001',
                'concurrent_users': 50,
                'expected_no_conflicts': True
            },
            'bug_reference': 'https://github.com/issues/003'
        },
        {
            'id': 'REG-004',
            'name': 'memory_leak_large_files',
            'description': 'Test for memory leaks with large file processing',
            'category': 'performance',
            'test_data': {
                'file_sizes_mb': [10, 25, 50, 100],
                'max_memory_increase_mb': 200
            },
            'bug_reference': 'https://github.com/issues/004'
        },
        {
            'id': 'REG-005',
            'name': 'rate_limit_edge_cases',
            'description': 'Test rate limiting edge cases',
            'category': 'security',
            'test_data': {
                'burst_requests': 1000,
                'time_window_seconds': 1,
                'expected_rate_limited': True
            },
            'bug_reference': 'https://github.com/issues/005'
        }
    ]


def generate_edge_cases() -> Dict[str, List[Dict[str, Any]]]:
    """Generate edge case test data."""
    return {
        'filenames': [
            {'name': '', 'description': 'Empty filename'},
            {'name': '.', 'description': 'Single dot'},
            {'name': '..', 'description': 'Double dot'},
            {'name': 'a' * 256, 'description': 'Very long filename'},
            {'name': 'file\x00name.txt', 'description': 'Null byte in filename'},
            {'name': 'file\nname.txt', 'description': 'Newline in filename'},
            {'name': 'file\tname.txt', 'description': 'Tab in filename'},
            {'name': 'CON.txt', 'description': 'Windows reserved name'},
            {'name': 'aux.txt', 'description': 'Windows reserved name'},
            {'name': 'file name.txt', 'description': 'Space in filename'},
            {'name': 'файл.txt', 'description': 'Cyrillic filename'},
            {'name': '文件.txt', 'description': 'Chinese filename'},
            {'name': '🔥📁.txt', 'description': 'Emoji in filename'},
        ],
        'queries': [
            {'query': '', 'description': 'Empty query'},
            {'query': ' ', 'description': 'Whitespace only query'},
            {'query': 'a', 'description': 'Single character query'},
            {'query': 'a' * 10000, 'description': 'Very long query'},
            {'query': '🤔💭🔍', 'description': 'Emoji only query'},
            {'query': '这是一个中文查询', 'description': 'Chinese query'},
            {'query': 'SELECT * FROM users;', 'description': 'SQL-like query'},
            {'query': '<script>alert("xss")</script>', 'description': 'XSS attempt'},
            {'query': '../../../etc/passwd', 'description': 'Path traversal attempt'},
        ],
        'file_contents': [
            {'content': b'', 'description': 'Empty file'},
            {'content': b'\x00' * 1024, 'description': 'Null bytes'},
            {'content': b'\xFF' * 1024, 'description': 'High bytes'},
            {'content': b'A' * (10 * 1024 * 1024), 'description': '10MB file'},
            {'content': 'Unicode content: 测试 🔥 café'.encode('utf-8'), 'description': 'Unicode content'},
            {'content': b'MZ\x90\x00', 'description': 'Executable header'},
            {'content': b'%PDF-1.4', 'description': 'PDF header'},
            {'content': b'\x89PNG\r\n\x1a\n', 'description': 'PNG header'},
        ]
    }


def save_test_data(data: Dict[str, Any], output_dir: Path):
    """Save test data to files."""
    output_dir.mkdir(exist_ok=True, parents=True)
    
    for category, items in data.items():
        output_file = output_dir / f"{category}.json"
        
        # Convert bytes to base64 for JSON serialization
        def serialize_item(item):
            if isinstance(item, dict):
                return {k: serialize_item(v) for k, v in item.items()}
            elif isinstance(item, list):
                return [serialize_item(i) for i in item]
            elif isinstance(item, bytes):
                import base64
                return {'__type__': 'bytes', 'data': base64.b64encode(item).decode()}
            else:
                return item
        
        serializable_items = serialize_item(items)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(serializable_items, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"Generated {len(items) if isinstance(items, list) else 'data'} items in {output_file}")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Generate test data for RAG-Anything API')
    parser.add_argument('--output-dir', '-o', type=Path, default='test_data',
                        help='Output directory for test data')
    parser.add_argument('--users', type=int, default=100,
                        help='Number of test users to generate')
    parser.add_argument('--files', type=int, default=50,
                        help='Number of test files to generate')
    parser.add_argument('--documents', type=int, default=200,
                        help='Number of test documents to generate')
    parser.add_argument('--queries', type=int, default=500,
                        help='Number of test queries to generate')
    parser.add_argument('--knowledge-bases', type=int, default=20,
                        help='Number of test knowledge bases to generate')
    parser.add_argument('--categories', nargs='*', 
                        choices=['users', 'files', 'documents', 'queries', 'kbs', 
                                'security', 'performance', 'regression', 'edge_cases', 'all'],
                        default=['all'],
                        help='Categories of test data to generate')
    
    args = parser.parse_args()
    
    print(f"Generating test data in {args.output_dir}")
    
    test_data = {}
    categories = args.categories if 'all' not in args.categories else [
        'users', 'files', 'documents', 'queries', 'kbs', 
        'security', 'performance', 'regression', 'edge_cases'
    ]
    
    for category in categories:
        print(f"Generating {category}...")
        
        if category == 'users':
            test_data['users'] = generate_users(args.users)
        elif category == 'files':
            test_data['files'] = generate_files(args.files)
        elif category == 'documents':
            test_data['documents'] = generate_documents(args.documents)
        elif category == 'queries':
            test_data['queries'] = generate_queries(args.queries)
        elif category == 'kbs':
            test_data['knowledge_bases'] = generate_knowledge_bases(args.knowledge_bases)
        elif category == 'security':
            test_data['security_payloads'] = generate_security_payloads()
        elif category == 'performance':
            test_data['performance_scenarios'] = generate_performance_scenarios()
        elif category == 'regression':
            test_data['regression_test_cases'] = generate_regression_test_cases()
        elif category == 'edge_cases':
            edge_cases = generate_edge_cases()
            for edge_category, edge_data in edge_cases.items():
                test_data[f'edge_cases_{edge_category}'] = edge_data
    
    # Save all data
    save_test_data(test_data, args.output_dir)
    
    print(f"\nTest data generation complete!")
    print(f"Output directory: {args.output_dir}")
    print(f"Generated {len(test_data)} categories of test data")
    
    # Generate summary
    summary = {
        'generated_at': str(Path.cwd()),
        'total_categories': len(test_data),
        'categories': list(test_data.keys()),
        'item_counts': {k: len(v) if isinstance(v, list) else 'N/A' for k, v in test_data.items()}
    }
    
    summary_file = args.output_dir / 'summary.json'
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    
    print(f"Summary saved to: {summary_file}")


if __name__ == '__main__':
    main()