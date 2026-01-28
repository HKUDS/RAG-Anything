.PHONY: mock-test
mock-test:
	uv run python api/core_endpoint_test.py api/datasets/patient_records_small.xlsx

.PHONY: server
server:
	@echo "Starting RAGAnything API server..."
	@echo "Server will be available at http://localhost:8000"
	@echo "Press Ctrl+C to gracefully stop the server"
	uv run uvicorn api.app:app --reload

.PHONY: stop
stop:
	@echo "Stopping all services..."
	@pkill -f "uvicorn api.app:app" || true

.PHONY: lint
lint:
	uv run ruff check . --fix --ignore=E402
