"""Test reporting and metrics generation utilities."""

import json
import csv
import html
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from jinja2 import Template


@dataclass
class TestMetrics:
    """Data class for test metrics."""
    test_name: str
    status: str
    duration: float
    memory_peak_mb: float
    cpu_percent: float
    error_message: Optional[str] = None
    category: str = 'general'
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class PerformanceMetrics:
    """Data class for performance test metrics."""
    test_name: str
    operations_per_second: float
    avg_response_time: float
    max_response_time: float
    min_response_time: float
    success_rate: float
    error_count: int
    total_operations: int
    memory_usage_mb: float
    cpu_usage_percent: float
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class SecurityTestResult:
    """Data class for security test results."""
    test_name: str
    attack_type: str
    payload: str
    expected_result: str
    actual_result: str
    status: str  # 'passed', 'failed', 'blocked'
    response_code: int
    blocked_by: Optional[str] = None  # 'rate_limit', 'input_validation', etc.
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class TestReporter:
    """Main test reporting class."""
    
    def __init__(self, output_dir: str = "test_reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Storage for different types of metrics
        self.test_metrics: List[TestMetrics] = []
        self.performance_metrics: List[PerformanceMetrics] = []
        self.security_results: List[SecurityTestResult] = []
        self.coverage_data: Dict[str, Any] = {}
    
    def add_test_metric(self, metric: TestMetrics):
        """Add a test metric."""
        self.test_metrics.append(metric)
    
    def add_performance_metric(self, metric: PerformanceMetrics):
        """Add a performance metric."""
        self.performance_metrics.append(metric)
    
    def add_security_result(self, result: SecurityTestResult):
        """Add a security test result."""
        self.security_results.append(result)
    
    def set_coverage_data(self, coverage: Dict[str, Any]):
        """Set coverage data."""
        self.coverage_data = coverage
    
    def generate_summary_report(self) -> Dict[str, Any]:
        """Generate a summary report of all metrics."""
        total_tests = len(self.test_metrics)
        passed_tests = sum(1 for m in self.test_metrics if m.status == 'passed')
        failed_tests = sum(1 for m in self.test_metrics if m.status == 'failed')
        
        # Performance summary
        avg_ops_per_sec = (
            sum(m.operations_per_second for m in self.performance_metrics) / len(self.performance_metrics)
            if self.performance_metrics else 0
        )
        
        avg_response_time = (
            sum(m.avg_response_time for m in self.performance_metrics) / len(self.performance_metrics)
            if self.performance_metrics else 0
        )
        
        # Security summary
        security_passed = sum(1 for r in self.security_results if r.status == 'passed')
        security_blocked = sum(1 for r in self.security_results if r.status == 'blocked')
        security_failed = sum(1 for r in self.security_results if r.status == 'failed')
        
        return {
            'summary': {
                'total_tests': total_tests,
                'passed_tests': passed_tests,
                'failed_tests': failed_tests,
                'success_rate': passed_tests / total_tests if total_tests > 0 else 0,
                'total_duration': sum(m.duration for m in self.test_metrics),
            },
            'performance': {
                'avg_operations_per_second': avg_ops_per_sec,
                'avg_response_time_ms': avg_response_time * 1000,
                'performance_tests_count': len(self.performance_metrics),
            },
            'security': {
                'total_security_tests': len(self.security_results),
                'passed': security_passed,
                'blocked': security_blocked,
                'failed': security_failed,
                'security_score': (security_passed + security_blocked) / len(self.security_results) if self.security_results else 0,
            },
            'coverage': self.coverage_data,
            'generated_at': datetime.utcnow().isoformat(),
        }
    
    def export_to_json(self, filename: str = "test_report.json"):
        """Export all data to JSON."""
        report_data = {
            'summary': self.generate_summary_report(),
            'test_metrics': [asdict(m) for m in self.test_metrics],
            'performance_metrics': [asdict(m) for m in self.performance_metrics],
            'security_results': [asdict(r) for r in self.security_results],
        }
        
        # Convert datetime objects to strings
        report_data = self._serialize_datetime(report_data)
        
        output_file = self.output_dir / filename
        with open(output_file, 'w') as f:
            json.dump(report_data, f, indent=2, default=str)
        
        return output_file
    
    def export_to_csv(self):
        """Export metrics to CSV files."""
        # Export test metrics
        if self.test_metrics:
            test_csv = self.output_dir / "test_metrics.csv"
            with open(test_csv, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=asdict(self.test_metrics[0]).keys())
                writer.writeheader()
                for metric in self.test_metrics:
                    writer.writerow(asdict(metric))
        
        # Export performance metrics
        if self.performance_metrics:
            perf_csv = self.output_dir / "performance_metrics.csv"
            with open(perf_csv, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=asdict(self.performance_metrics[0]).keys())
                writer.writeheader()
                for metric in self.performance_metrics:
                    writer.writerow(asdict(metric))
        
        # Export security results
        if self.security_results:
            security_csv = self.output_dir / "security_results.csv"
            with open(security_csv, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=asdict(self.security_results[0]).keys())
                writer.writeheader()
                for result in self.security_results:
                    writer.writerow(asdict(result))
    
    def generate_html_report(self, template_path: Optional[str] = None) -> Path:
        """Generate an HTML report."""
        if template_path:
            with open(template_path) as f:
                template_content = f.read()
        else:
            template_content = self._get_default_html_template()
        
        template = Template(template_content)
        
        # Prepare data for template
        summary = self.generate_summary_report()
        
        # Group tests by category
        tests_by_category = {}
        for metric in self.test_metrics:
            category = metric.category
            if category not in tests_by_category:
                tests_by_category[category] = []
            tests_by_category[category].append(metric)
        
        # Top performing and problematic tests
        top_performing = sorted(
            self.performance_metrics, 
            key=lambda x: x.operations_per_second, 
            reverse=True
        )[:5]
        
        slowest_tests = sorted(
            self.test_metrics, 
            key=lambda x: x.duration, 
            reverse=True
        )[:5]
        
        html_content = template.render(
            summary=summary,
            tests_by_category=tests_by_category,
            performance_metrics=self.performance_metrics,
            security_results=self.security_results,
            top_performing=top_performing,
            slowest_tests=slowest_tests,
            generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        )
        
        output_file = self.output_dir / "test_report.html"
        with open(output_file, 'w') as f:
            f.write(html_content)
        
        return output_file
    
    def generate_performance_chart_data(self) -> Dict[str, Any]:
        """Generate data for performance charts."""
        if not self.performance_metrics:
            return {}
        
        # Response time over time
        response_times = [
            {
                'timestamp': m.timestamp.isoformat(),
                'avg_response_time': m.avg_response_time * 1000,  # Convert to ms
                'test_name': m.test_name,
            }
            for m in sorted(self.performance_metrics, key=lambda x: x.timestamp)
        ]
        
        # Operations per second
        throughput_data = [
            {
                'test_name': m.test_name,
                'operations_per_second': m.operations_per_second,
                'success_rate': m.success_rate,
            }
            for m in self.performance_metrics
        ]
        
        # Resource usage
        resource_usage = [
            {
                'test_name': m.test_name,
                'memory_usage_mb': m.memory_usage_mb,
                'cpu_usage_percent': m.cpu_usage_percent,
                'timestamp': m.timestamp.isoformat(),
            }
            for m in self.performance_metrics
        ]
        
        return {
            'response_times': response_times,
            'throughput': throughput_data,
            'resource_usage': resource_usage,
        }
    
    def generate_security_summary(self) -> Dict[str, Any]:
        """Generate security test summary."""
        if not self.security_results:
            return {}
        
        # Group by attack type
        by_attack_type = {}
        for result in self.security_results:
            attack_type = result.attack_type
            if attack_type not in by_attack_type:
                by_attack_type[attack_type] = {'passed': 0, 'failed': 0, 'blocked': 0}
            by_attack_type[attack_type][result.status] += 1
        
        # Most vulnerable endpoints
        vulnerable_tests = [r for r in self.security_results if r.status == 'failed']
        
        # Best protected endpoints
        protected_tests = [r for r in self.security_results if r.status == 'blocked']
        
        return {
            'by_attack_type': by_attack_type,
            'vulnerable_tests': vulnerable_tests[:10],  # Top 10 most vulnerable
            'protected_tests': protected_tests[:10],    # Top 10 best protected
            'total_attacks_tested': len(self.security_results),
            'total_blocked': len(protected_tests),
            'total_failed': len(vulnerable_tests),
        }
    
    def _serialize_datetime(self, obj):
        """Recursively serialize datetime objects to strings."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: self._serialize_datetime(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_datetime(item) for item in obj]
        else:
            return obj
    
    def _get_default_html_template(self) -> str:
        """Get default HTML template for reports."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAG-Anything API Test Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { text-align: center; border-bottom: 2px solid #3498db; padding-bottom: 20px; margin-bottom: 30px; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .metric-card { background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid #3498db; }
        .metric-value { font-size: 2em; font-weight: bold; color: #2c3e50; }
        .metric-label { color: #7f8c8d; font-size: 0.9em; }
        .section { margin-bottom: 30px; }
        .section h2 { color: #2c3e50; border-bottom: 1px solid #ecf0f1; padding-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ecf0f1; }
        th { background-color: #3498db; color: white; }
        .status-passed { color: #27ae60; font-weight: bold; }
        .status-failed { color: #e74c3c; font-weight: bold; }
        .status-blocked { color: #f39c12; font-weight: bold; }
        .progress-bar { width: 100%; height: 20px; background-color: #ecf0f1; border-radius: 10px; overflow: hidden; }
        .progress-fill { height: 100%; background: linear-gradient(90deg, #27ae60, #2ecc71); transition: width 0.3s; }
        .chart-placeholder { height: 300px; background: #f8f9fa; border: 2px dashed #bdc3c7; display: flex; align-items: center; justify-content: center; color: #7f8c8d; margin: 20px 0; }
        .footer { text-align: center; margin-top: 40px; color: #7f8c8d; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>RAG-Anything API Test Report</h1>
            <p>Generated on {{ generated_at }}</p>
        </div>
        
        <div class="section">
            <h2>Summary</h2>
            <div class="summary">
                <div class="metric-card">
                    <div class="metric-value">{{ summary.summary.total_tests }}</div>
                    <div class="metric-label">Total Tests</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{{ "%.1f"|format(summary.summary.success_rate * 100) }}%</div>
                    <div class="metric-label">Success Rate</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{{ "%.2f"|format(summary.summary.total_duration) }}s</div>
                    <div class="metric-label">Total Duration</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{{ "%.1f"|format(summary.performance.avg_operations_per_second) }}</div>
                    <div class="metric-label">Avg Ops/Second</div>
                </div>
            </div>
            
            <div class="progress-bar">
                <div class="progress-fill" style="width: {{ summary.summary.success_rate * 100 }}%"></div>
            </div>
        </div>
        
        <div class="section">
            <h2>Test Results by Category</h2>
            {% for category, tests in tests_by_category.items() %}
            <h3>{{ category.title() }} Tests</h3>
            <table>
                <thead>
                    <tr>
                        <th>Test Name</th>
                        <th>Status</th>
                        <th>Duration (s)</th>
                        <th>Memory (MB)</th>
                        <th>Error</th>
                    </tr>
                </thead>
                <tbody>
                    {% for test in tests %}
                    <tr>
                        <td>{{ test.test_name }}</td>
                        <td class="status-{{ test.status }}">{{ test.status.upper() }}</td>
                        <td>{{ "%.3f"|format(test.duration) }}</td>
                        <td>{{ "%.1f"|format(test.memory_peak_mb) }}</td>
                        <td>{{ test.error_message or '' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% endfor %}
        </div>
        
        {% if performance_metrics %}
        <div class="section">
            <h2>Performance Metrics</h2>
            <div class="chart-placeholder">Performance Charts Would Appear Here</div>
            <table>
                <thead>
                    <tr>
                        <th>Test Name</th>
                        <th>Ops/Second</th>
                        <th>Avg Response (ms)</th>
                        <th>Max Response (ms)</th>
                        <th>Success Rate</th>
                        <th>Memory (MB)</th>
                    </tr>
                </thead>
                <tbody>
                    {% for metric in performance_metrics %}
                    <tr>
                        <td>{{ metric.test_name }}</td>
                        <td>{{ "%.1f"|format(metric.operations_per_second) }}</td>
                        <td>{{ "%.1f"|format(metric.avg_response_time * 1000) }}</td>
                        <td>{{ "%.1f"|format(metric.max_response_time * 1000) }}</td>
                        <td>{{ "%.1f"|format(metric.success_rate * 100) }}%</td>
                        <td>{{ "%.1f"|format(metric.memory_usage_mb) }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
        
        {% if security_results %}
        <div class="section">
            <h2>Security Test Results</h2>
            <div class="summary">
                <div class="metric-card">
                    <div class="metric-value">{{ summary.security.total_security_tests }}</div>
                    <div class="metric-label">Security Tests</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{{ summary.security.blocked }}</div>
                    <div class="metric-label">Attacks Blocked</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{{ summary.security.failed }}</div>
                    <div class="metric-label">Vulnerabilities</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">{{ "%.1f"|format(summary.security.security_score * 100) }}%</div>
                    <div class="metric-label">Security Score</div>
                </div>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>Test Name</th>
                        <th>Attack Type</th>
                        <th>Status</th>
                        <th>Response Code</th>
                        <th>Blocked By</th>
                    </tr>
                </thead>
                <tbody>
                    {% for result in security_results[:20] %}
                    <tr>
                        <td>{{ result.test_name }}</td>
                        <td>{{ result.attack_type }}</td>
                        <td class="status-{{ result.status }}">{{ result.status.upper() }}</td>
                        <td>{{ result.response_code }}</td>
                        <td>{{ result.blocked_by or '' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
        
        <div class="footer">
            <p>Report generated by RAG-Anything API Test Suite</p>
        </div>
    </div>
</body>
</html>
        """


class CoverageReporter:
    """Coverage reporting utilities."""
    
    def __init__(self, coverage_file: str = ".coverage"):
        self.coverage_file = coverage_file
    
    def generate_coverage_report(self) -> Dict[str, Any]:
        """Generate coverage report from coverage.py data."""
        try:
            import coverage
            cov = coverage.Coverage(data_file=self.coverage_file)
            cov.load()
            
            # Get coverage data
            total_statements = 0
            total_missing = 0
            file_coverage = {}
            
            for filename in cov.get_data().measured_files():
                if 'app/' in filename:  # Only include app files
                    analysis = cov.analysis2(filename)
                    statements = len(analysis.statements)
                    missing = len(analysis.missing)
                    
                    total_statements += statements
                    total_missing += missing
                    
                    file_coverage[filename] = {
                        'statements': statements,
                        'missing': missing,
                        'coverage': (statements - missing) / statements * 100 if statements > 0 else 0
                    }
            
            overall_coverage = (total_statements - total_missing) / total_statements * 100 if total_statements > 0 else 0
            
            return {
                'overall_coverage': overall_coverage,
                'total_statements': total_statements,
                'total_missing': total_missing,
                'file_coverage': file_coverage,
            }
            
        except ImportError:
            return {'error': 'Coverage.py not available'}
        except Exception as e:
            return {'error': f'Failed to generate coverage report: {e}'}


class BenchmarkReporter:
    """Benchmark reporting utilities."""
    
    def __init__(self, output_dir: str = "benchmark_reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.benchmarks: List[Dict[str, Any]] = []
    
    def add_benchmark(self, name: str, stats: Dict[str, Any]):
        """Add benchmark results."""
        self.benchmarks.append({
            'name': name,
            'timestamp': datetime.utcnow(),
            'stats': stats,
        })
    
    def compare_with_baseline(self, baseline_file: str) -> Dict[str, Any]:
        """Compare current benchmarks with baseline."""
        baseline_path = Path(baseline_file)
        
        if not baseline_path.exists():
            return {'error': 'Baseline file not found'}
        
        try:
            with open(baseline_path) as f:
                baseline_data = json.load(f)
            
            comparisons = {}
            
            for benchmark in self.benchmarks:
                name = benchmark['name']
                current_stats = benchmark['stats']
                
                # Find baseline benchmark
                baseline_benchmark = next(
                    (b for b in baseline_data.get('benchmarks', []) if b['name'] == name),
                    None
                )
                
                if baseline_benchmark:
                    baseline_stats = baseline_benchmark['stats']
                    
                    comparison = {
                        'name': name,
                        'current': current_stats,
                        'baseline': baseline_stats,
                        'changes': {},
                    }
                    
                    # Compare key metrics
                    for metric in ['mean', 'stddev', 'min', 'max']:
                        if metric in current_stats and metric in baseline_stats:
                            current_val = current_stats[metric]
                            baseline_val = baseline_stats[metric]
                            change_percent = (current_val - baseline_val) / baseline_val * 100
                            
                            comparison['changes'][metric] = {
                                'absolute': current_val - baseline_val,
                                'percent': change_percent,
                                'improved': change_percent < 0,  # Lower is better for response times
                            }
                    
                    comparisons[name] = comparison
            
            return {'comparisons': comparisons}
            
        except Exception as e:
            return {'error': f'Failed to compare with baseline: {e}'}
    
    def save_as_baseline(self, filename: str = "benchmark_baseline.json"):
        """Save current benchmarks as baseline."""
        baseline_data = {
            'created_at': datetime.utcnow().isoformat(),
            'benchmarks': self.benchmarks,
        }
        
        output_file = self.output_dir / filename
        with open(output_file, 'w') as f:
            json.dump(baseline_data, f, indent=2, default=str)
        
        return output_file


# Global reporter instance
_global_reporter = None


def get_test_reporter() -> TestReporter:
    """Get the global test reporter instance."""
    global _global_reporter
    if _global_reporter is None:
        _global_reporter = TestReporter()
    return _global_reporter


def setup_test_reporting(output_dir: str = "test_reports"):
    """Setup test reporting with custom output directory."""
    global _global_reporter
    _global_reporter = TestReporter(output_dir)
    return _global_reporter


def finalize_test_reports():
    """Finalize and generate all test reports."""
    reporter = get_test_reporter()
    
    # Generate all report formats
    json_report = reporter.export_to_json()
    html_report = reporter.generate_html_report()
    reporter.export_to_csv()
    
    print(f"Test reports generated:")
    print(f"  JSON: {json_report}")
    print(f"  HTML: {html_report}")
    print(f"  CSV files in: {reporter.output_dir}")
    
    return {
        'json': json_report,
        'html': html_report,
        'csv_dir': reporter.output_dir,
    }