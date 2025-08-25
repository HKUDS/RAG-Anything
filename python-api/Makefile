# RAG-Anything API Makefile
# Provides convenient commands for development and testing

.PHONY: help install test test-unit test-integration test-security test-e2e test-performance
.PHONY: test-all test-quick lint format type-check security-scan clean coverage
.PHONY: dev build docker-build docker-test serve docs

# Default target
help: ## Show this help message
	@echo "RAG-Anything API Development Commands"
	@echo "====================================="
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Examples:"
	@echo "  make install          # Install all dependencies"
	@echo "  make test-quick       # Run quick test suite"
	@echo "  make test-all         # Run comprehensive tests"
	@echo "  make lint format      # Check and fix code style"

# Installation
install: ## Install all dependencies for development
	@echo "Installing dependencies..."
	pip install -e .[dev]
	pre-commit install

install-prod: ## Install production dependencies only
	pip install -e .

# Testing
test: test-unit ## Run default test suite (unit tests)

test-unit: ## Run unit tests with coverage
	@echo "Running unit tests..."
	./scripts/run_tests.sh --type unit --verbose

test-integration: ## Run integration tests
	@echo "Running integration tests..."
	./scripts/run_tests.sh --type integration --verbose

test-security: ## Run security tests
	@echo "Running security tests..."
	./scripts/run_tests.sh --type security --verbose

test-e2e: ## Run end-to-end tests
	@echo "Running e2e tests..."
	./scripts/run_tests.sh --type e2e --verbose

test-performance: ## Run performance and load tests
	@echo "Running performance tests..."
	./scripts/run_tests.sh --type performance --verbose

test-all: ## Run all tests including performance and security
	@echo "Running comprehensive test suite..."
	./scripts/run_tests.sh --type all --verbose

test-quick: ## Run quick test suite (unit + integration)
	@echo "Running quick test suite..."
	pytest tests/unit/ tests/integration/ -v --tb=short --maxfail=5

test-parallel: ## Run tests in parallel
	@echo "Running tests in parallel..."
	pytest tests/ -n auto -v

test-watch: ## Run tests in watch mode
	@echo "Running tests in watch mode (install pytest-watch: pip install pytest-watch)"
	ptw tests/ -- -v --tb=short

# Code Quality
lint: ## Run code linting
	@echo "Running linting..."
	ruff check app/ tests/
	black --check app/ tests/

format: ## Auto-format code
	@echo "Formatting code..."
	black app/ tests/
	ruff --fix app/ tests/

type-check: ## Run type checking
	@echo "Running type checks..."
	mypy app/

quality-check: lint type-check ## Run all code quality checks

# Security
security-scan: ## Run security scans
	@echo "Running security scans..."
	bandit -r app/ -ll
	safety check

# Coverage
coverage: ## Generate coverage report
	@echo "Generating coverage report..."
	pytest tests/unit/ tests/integration/ --cov=app --cov-report=html --cov-report=term
	@echo "Coverage report generated in htmlcov/"

coverage-open: coverage ## Open coverage report in browser
	@echo "Opening coverage report..."
	@which xdg-open > /dev/null && xdg-open htmlcov/index.html || \
	which open > /dev/null && open htmlcov/index.html || \
	echo "Please open htmlcov/index.html in your browser"

# Development
dev: ## Start development server with auto-reload
	@echo "Starting development server..."
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-debug: ## Start development server in debug mode
	@echo "Starting debug server..."
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --log-level debug

serve: ## Start production server
	@echo "Starting production server..."
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# Docker
docker-build: ## Build Docker image
	@echo "Building Docker image..."
	docker build -t raganything-api:latest .

docker-test: docker-build ## Test Docker image
	@echo "Testing Docker image..."
	docker run --rm -d --name raganything-test -p 8001:8000 \
		-e TESTING=1 raganything-api:latest
	@echo "Waiting for container to start..."
	@sleep 5
	@curl -f http://localhost:8001/api/v1/health && echo "✓ Container health check passed" || echo "✗ Container health check failed"
	@docker stop raganything-test

docker-run: ## Run Docker container
	@echo "Running Docker container..."
	docker run --rm -p 8000:8000 \
		-e REDIS_URL=redis://host.docker.internal:6379 \
		raganything-api:latest

# Database
db-setup: ## Setup test database (Redis)
	@echo "Setting up Redis for testing..."
	@which redis-server > /dev/null || (echo "Redis not installed. Install with: apt-get install redis-server" && exit 1)
	@redis-cli ping > /dev/null 2>&1 && echo "✓ Redis is running" || (echo "✗ Redis is not running. Start with: redis-server" && exit 1)

# Documentation
docs: ## Generate API documentation
	@echo "Generating API documentation..."
	@echo "Starting server for documentation generation..."
	uvicorn app.main:app --host 0.0.0.0 --port 8000 &
	@sleep 3
	@echo "Documentation available at: http://localhost:8000/docs"
	@echo "ReDoc available at: http://localhost:8000/redoc"
	@echo "OpenAPI spec at: http://localhost:8000/openapi.json"

# Benchmarking
benchmark: ## Run benchmark tests
	@echo "Running benchmark tests..."
	pytest tests/performance/ --benchmark-only --benchmark-sort=mean

benchmark-compare: ## Compare benchmarks with baseline
	@echo "Comparing with benchmark baseline..."
	pytest tests/performance/ --benchmark-only --benchmark-compare --benchmark-sort=mean

benchmark-save: ## Save current benchmarks as baseline
	@echo "Saving benchmark baseline..."
	pytest tests/performance/ --benchmark-only --benchmark-save=baseline

# Load Testing
load-test: ## Run load tests with Locust
	@echo "Starting load tests..."
	@echo "Starting API server..."
	uvicorn app.main:app --host 0.0.0.0 --port 8000 &
	@sleep 5
	@echo "Running Locust load tests..."
	cd tests/performance && locust -f locustfile.py --host http://localhost:8000 \
		--users 50 --spawn-rate 5 --run-time 2m --headless \
		--html ../../load_test_report.html
	@echo "Load test report generated: load_test_report.html"

# Cleanup
clean: ## Clean up generated files and caches
	@echo "Cleaning up..."
	rm -rf htmlcov/
	rm -rf test_reports/
	rm -rf .coverage
	rm -rf .pytest_cache/
	rm -rf temp_test_data/
	rm -rf *.log
	find . -type d -name "__pycache__" -delete 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage.*" -delete 2>/dev/null || true

clean-all: clean ## Clean everything including Docker images
	docker image rm raganything-api:latest 2>/dev/null || true
	docker system prune -f

# CI/CD Simulation
ci-test: ## Simulate CI/CD pipeline locally
	@echo "Simulating CI/CD pipeline..."
	make clean
	make install
	make quality-check
	make test-unit
	make test-integration
	make test-security
	make security-scan
	make docker-build
	make docker-test
	@echo "✓ CI/CD simulation completed successfully"

# Release
release-check: ## Check if ready for release
	@echo "Checking release readiness..."
	make quality-check
	make test-all
	make security-scan
	@echo "✓ Release checks passed"

# Development utilities
shell: ## Start interactive Python shell with app context
	@echo "Starting interactive shell..."
	python -c "from app.main import app; import IPython; IPython.embed()"

requirements: ## Generate requirements.txt from pyproject.toml
	@echo "Generating requirements.txt..."
	pip-compile pyproject.toml

update-deps: ## Update all dependencies
	@echo "Updating dependencies..."
	pip-compile --upgrade pyproject.toml
	pip install -e .[dev]

# Monitoring
monitor: ## Start monitoring dashboard (if implemented)
	@echo "Monitoring dashboard not implemented yet"
	@echo "Available metrics at: http://localhost:8000/metrics"

# Setup for new developers
setup: ## Complete setup for new developers
	@echo "Setting up development environment..."
	@echo "1. Installing dependencies..."
	make install
	@echo "2. Setting up database..."
	make db-setup
	@echo "3. Running initial tests..."
	make test-quick
	@echo "4. Checking code quality..."
	make quality-check
	@echo ""
	@echo "✓ Development environment ready!"
	@echo ""
	@echo "Next steps:"
	@echo "  make dev          # Start development server"
	@echo "  make test-watch   # Run tests in watch mode"
	@echo "  make docs         # View API documentation"

# Aliases for convenience
t: test ## Alias for test
ta: test-all ## Alias for test-all
tq: test-quick ## Alias for test-quick
l: lint ## Alias for lint
f: format ## Alias for format
d: dev ## Alias for dev
c: clean ## Alias for clean