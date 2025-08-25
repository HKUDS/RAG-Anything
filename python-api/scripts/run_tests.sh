#!/bin/bash
"""
Comprehensive test runner script for RAG-Anything API
Supports different test types and environments
"""

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
TEST_TYPE="all"
ENVIRONMENT="test"
COVERAGE_THRESHOLD=85
PARALLEL_WORKERS=auto
VERBOSE=false
CLEAN=false
REPORT_DIR="test_reports"
EXIT_ON_FAIL=true

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--type)
            TEST_TYPE="$2"
            shift 2
            ;;
        -e|--env)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -c|--coverage)
            COVERAGE_THRESHOLD="$2"
            shift 2
            ;;
        -j|--workers)
            PARALLEL_WORKERS="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        --clean)
            CLEAN=true
            shift
            ;;
        --continue-on-fail)
            EXIT_ON_FAIL=false
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -t, --type TYPE         Test type: unit, integration, security, e2e, performance, all"
            echo "  -e, --env ENV           Environment: test, ci, local"
            echo "  -c, --coverage NUM      Coverage threshold (default: 85)"
            echo "  -j, --workers NUM       Number of parallel workers (default: auto)"
            echo "  -v, --verbose           Verbose output"
            echo "  --clean                 Clean previous test artifacts"
            echo "  --continue-on-fail      Continue running tests even if some fail"
            echo "  -h, --help              Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --type unit --verbose"
            echo "  $0 --type performance --env ci"
            echo "  $0 --clean --type all"
            exit 0
            ;;
        *)
            echo "Unknown option $1"
            exit 1
            ;;
    esac
done

# Functions
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}✓${NC} $1"
}

error() {
    echo -e "${RED}✗${NC} $1"
}

warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

check_dependencies() {
    log "Checking dependencies..."
    
    # Check Python version
    python_version=$(python --version 2>&1 | cut -d' ' -f2)
    if [[ $(echo $python_version | cut -d'.' -f1) -lt 3 ]] || [[ $(echo $python_version | cut -d'.' -f2) -lt 9 ]]; then
        error "Python 3.9+ required, found $python_version"
        exit 1
    fi
    success "Python $python_version found"
    
    # Check if pytest is installed
    if ! python -c "import pytest" 2>/dev/null; then
        error "pytest not found. Install with: pip install -e .[dev]"
        exit 1
    fi
    success "pytest found"
    
    # Check Redis connection
    if [[ "$ENVIRONMENT" != "ci" ]]; then
        if ! redis-cli ping >/dev/null 2>&1; then
            warning "Redis not available. Some tests may be skipped."
        else
            success "Redis connection OK"
        fi
    fi
}

setup_environment() {
    log "Setting up test environment..."
    
    # Set environment variables
    export TESTING=1
    export PYTHONPATH="${PYTHONPATH}:$(pwd)"
    
    case $ENVIRONMENT in
        ci)
            export REDIS_URL="redis://localhost:6379/15"
            export LOG_LEVEL="WARNING"
            ;;
        test)
            export REDIS_URL="redis://localhost:6379/15"
            export LOG_LEVEL="INFO"
            ;;
        local)
            export LOG_LEVEL="DEBUG"
            ;;
    esac
    
    # Create necessary directories
    mkdir -p "$REPORT_DIR"
    mkdir -p "temp_test_data"
    mkdir -p "htmlcov"
    
    success "Environment configured for $ENVIRONMENT"
}

clean_artifacts() {
    if [[ "$CLEAN" == true ]]; then
        log "Cleaning previous test artifacts..."
        rm -rf htmlcov/
        rm -rf "$REPORT_DIR"/*
        rm -rf .coverage
        rm -rf .pytest_cache/
        rm -rf temp_test_data/
        find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        success "Artifacts cleaned"
    fi
}

run_unit_tests() {
    log "Running unit tests..."
    
    local args=()
    [[ "$VERBOSE" == true ]] && args+=(-v)
    [[ "$PARALLEL_WORKERS" != "auto" ]] && args+=(-n "$PARALLEL_WORKERS")
    
    if python -m pytest tests/unit/ \
        "${args[@]}" \
        --cov=app \
        --cov-report=html:htmlcov/unit \
        --cov-report=xml:coverage_unit.xml \
        --cov-report=term-missing \
        --cov-fail-under="$COVERAGE_THRESHOLD" \
        --junit-xml="$REPORT_DIR/unit_tests.xml" \
        --tb=short; then
        success "Unit tests passed"
        return 0
    else
        error "Unit tests failed"
        return 1
    fi
}

run_integration_tests() {
    log "Running integration tests..."
    
    local args=()
    [[ "$VERBOSE" == true ]] && args+=(-v)
    
    if python -m pytest tests/integration/ \
        "${args[@]}" \
        --cov=app \
        --cov-append \
        --cov-report=html:htmlcov/integration \
        --cov-report=xml:coverage_integration.xml \
        --junit-xml="$REPORT_DIR/integration_tests.xml" \
        -m integration; then
        success "Integration tests passed"
        return 0
    else
        error "Integration tests failed"
        return 1
    fi
}

run_security_tests() {
    log "Running security tests..."
    
    local args=()
    [[ "$VERBOSE" == true ]] && args+=(-v)
    
    if python -m pytest tests/security/ \
        "${args[@]}" \
        --junit-xml="$REPORT_DIR/security_tests.xml" \
        -m security; then
        success "Security tests passed"
        return 0
    else
        error "Security tests failed"
        return 1
    fi
}

run_e2e_tests() {
    log "Running end-to-end tests..."
    
    local args=()
    [[ "$VERBOSE" == true ]] && args+=(-v)
    
    if python -m pytest tests/e2e/ \
        "${args[@]}" \
        --junit-xml="$REPORT_DIR/e2e_tests.xml" \
        -m e2e \
        --maxfail=5; then
        success "E2E tests passed"
        return 0
    else
        error "E2E tests failed"
        return 1
    fi
}

run_performance_tests() {
    log "Running performance tests..."
    
    local args=()
    [[ "$VERBOSE" == true ]] && args+=(-v)
    
    if python -m pytest tests/performance/ \
        "${args[@]}" \
        --benchmark-only \
        --benchmark-json="$REPORT_DIR/benchmark.json" \
        --junit-xml="$REPORT_DIR/performance_tests.xml" \
        -m performance; then
        success "Performance tests passed"
        return 0
    else
        error "Performance tests failed"
        return 1
    fi
}

run_load_tests() {
    log "Running load tests..."
    
    # Start the API server in background
    log "Starting API server for load testing..."
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning &
    SERVER_PID=$!
    
    # Wait for server to start
    sleep 5
    
    # Check if server is running
    if ! curl -f http://localhost:8000/api/v1/health >/dev/null 2>&1; then
        error "Failed to start API server for load testing"
        kill $SERVER_PID 2>/dev/null || true
        return 1
    fi
    
    success "API server started (PID: $SERVER_PID)"
    
    # Run load tests
    cd tests/performance
    if locust -f locustfile.py --host http://localhost:8000 \
        --users 20 --spawn-rate 2 --run-time 1m --headless \
        --html "../../$REPORT_DIR/load_test.html" \
        --csv "../../$REPORT_DIR/load_test"; then
        success "Load tests completed"
        cd ../..
        kill $SERVER_PID 2>/dev/null || true
        return 0
    else
        error "Load tests failed"
        cd ../..
        kill $SERVER_PID 2>/dev/null || true
        return 1
    fi
}

run_code_quality_checks() {
    log "Running code quality checks..."
    
    # Black formatting check
    if black --check app/ tests/; then
        success "Code formatting check passed"
    else
        error "Code formatting check failed. Run 'black app/ tests/' to fix."
        return 1
    fi
    
    # Ruff linting
    if ruff check app/ tests/; then
        success "Linting check passed"
    else
        error "Linting check failed"
        return 1
    fi
    
    # MyPy type checking
    if mypy app/; then
        success "Type checking passed"
    else
        warning "Type checking failed (non-blocking)"
    fi
    
    return 0
}

run_security_scans() {
    log "Running security scans..."
    
    # Bandit security scan
    if bandit -r app/ -f json -o "$REPORT_DIR/bandit.json" >/dev/null 2>&1; then
        success "Bandit security scan passed"
    else
        warning "Bandit found potential security issues"
    fi
    
    # Safety dependency scan
    if safety check --json --output "$REPORT_DIR/safety.json" >/dev/null 2>&1; then
        success "Safety dependency scan passed"
    else
        warning "Safety found vulnerable dependencies"
    fi
    
    return 0
}

generate_reports() {
    log "Generating test reports..."
    
    # Generate coverage report
    if [[ -f ".coverage" ]]; then
        coverage html -d htmlcov/combined
        coverage xml -o coverage.xml
        coverage report --show-missing
        success "Coverage report generated"
    fi
    
    # Generate HTML test report using our custom reporter
    python -c "
import json
from pathlib import Path
from tests.utils.reporting import finalize_test_reports

try:
    reports = finalize_test_reports()
    print(f'✓ Test reports generated in {reports[\"csv_dir\"]}')
except Exception as e:
    print(f'⚠ Failed to generate custom reports: {e}')
"
    
    # List all generated reports
    log "Generated reports:"
    find "$REPORT_DIR" -type f -name "*.html" -o -name "*.json" -o -name "*.xml" | while read -r file; do
        echo "  - $file"
    done
}

main() {
    local exit_code=0
    local failed_tests=()
    
    echo -e "${BLUE}🧪 RAG-Anything API Test Suite${NC}"
    echo "=================================="
    echo "Test type: $TEST_TYPE"
    echo "Environment: $ENVIRONMENT"
    echo "Coverage threshold: $COVERAGE_THRESHOLD%"
    echo ""
    
    check_dependencies
    setup_environment
    clean_artifacts
    
    # Run tests based on type
    case $TEST_TYPE in
        unit)
            run_unit_tests || { failed_tests+=("unit"); [[ "$EXIT_ON_FAIL" == true ]] && exit_code=1; }
            ;;
        integration)
            run_integration_tests || { failed_tests+=("integration"); [[ "$EXIT_ON_FAIL" == true ]] && exit_code=1; }
            ;;
        security)
            run_security_tests || { failed_tests+=("security"); [[ "$EXIT_ON_FAIL" == true ]] && exit_code=1; }
            ;;
        e2e)
            run_e2e_tests || { failed_tests+=("e2e"); [[ "$EXIT_ON_FAIL" == true ]] && exit_code=1; }
            ;;
        performance)
            run_performance_tests || { failed_tests+=("performance"); [[ "$EXIT_ON_FAIL" == true ]] && exit_code=1; }
            run_load_tests || { failed_tests+=("load"); [[ "$EXIT_ON_FAIL" == true ]] && exit_code=1; }
            ;;
        quality)
            run_code_quality_checks || { failed_tests+=("quality"); [[ "$EXIT_ON_FAIL" == true ]] && exit_code=1; }
            run_security_scans || { failed_tests+=("security_scan"); [[ "$EXIT_ON_FAIL" == true ]] && exit_code=1; }
            ;;
        all)
            run_unit_tests || { failed_tests+=("unit"); [[ "$EXIT_ON_FAIL" == false ]] || exit_code=1; }
            run_integration_tests || { failed_tests+=("integration"); [[ "$EXIT_ON_FAIL" == false ]] || exit_code=1; }
            run_security_tests || { failed_tests+=("security"); [[ "$EXIT_ON_FAIL" == false ]] || exit_code=1; }
            run_e2e_tests || { failed_tests+=("e2e"); [[ "$EXIT_ON_FAIL" == false ]] || exit_code=1; }
            run_code_quality_checks || { failed_tests+=("quality"); [[ "$EXIT_ON_FAIL" == false ]] || exit_code=1; }
            run_security_scans || { failed_tests+=("security_scan"); [[ "$EXIT_ON_FAIL" == false ]] || exit_code=1; }
            ;;
        *)
            error "Unknown test type: $TEST_TYPE"
            error "Valid types: unit, integration, security, e2e, performance, quality, all"
            exit 1
            ;;
    esac
    
    generate_reports
    
    # Summary
    echo ""
    echo "=================================="
    if [[ ${#failed_tests[@]} -eq 0 ]]; then
        success "All tests passed! 🎉"
        echo "Coverage reports: htmlcov/"
        echo "Test reports: $REPORT_DIR/"
    else
        error "Some tests failed:"
        for test in "${failed_tests[@]}"; do
            echo "  - $test"
        done
        echo ""
        echo "Check the reports for details: $REPORT_DIR/"
        exit_code=1
    fi
    
    exit $exit_code
}

# Handle Ctrl+C gracefully
trap 'error "Test run interrupted"; exit 130' INT

# Run main function
main "$@"