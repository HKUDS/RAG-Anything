"""Unit tests for Docker containerization and compose configuration files.

Validates that Dockerfile, docker-compose.yml, entrypoint script, and .dockerignore
meet architectural and security requirements.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_structure():
    dockerfile_path = REPO_ROOT / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist at repository root"

    content = dockerfile_path.read_text(encoding="utf-8")

    # Multi-stage build verification
    assert "AS builder" in content, "Dockerfile must define builder stage"
    assert "AS runtime" in content, "Dockerfile must define runtime stage"

    # Security: unprivileged non-root user
    assert (
        "useradd" in content or "adduser" in content
    ), "Dockerfile must create non-root user"
    assert "USER appuser" in content, "Dockerfile must switch to unprivileged user"

    # Working directory
    assert "WORKDIR /app" in content, "Dockerfile must set /app workdir"

    # Entrypoint script
    assert "ENTRYPOINT" in content, "Dockerfile must configure ENTRYPOINT"


def test_docker_compose_structure():
    compose_path = REPO_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist at repository root"

    content = compose_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    assert "services" in parsed, "Compose file must define 'services'"
    assert (
        "raganything" in parsed["services"]
    ), "Compose file must contain 'raganything' service"

    service = parsed["services"]["raganything"]
    assert service.get("restart") == "no"

    # Verify volume mounts
    volumes = service.get("volumes", [])
    volume_targets = [v.split(":")[1] for v in volumes]
    assert "/app/rag_storage" in volume_targets
    assert "/app/parser_output" in volume_targets
    assert "/app/inputs" in volume_targets

    # Verify resource limits
    deploy = service.get("deploy", {})
    resources = deploy.get("resources", {})
    assert "limits" in resources, "Compose file should configure resource limits"


def test_dockerignore_structure():
    dockerignore_path = REPO_ROOT / ".dockerignore"
    assert dockerignore_path.exists(), ".dockerignore must exist at repository root"

    content = dockerignore_path.read_text(encoding="utf-8")
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert ".git" in lines
    assert ".venv" in lines
    assert "__pycache__" in lines
    assert "rag_storage/" in lines or "rag_storage" in lines
    assert "parser_output/" in lines or "parser_output" in lines


def test_env_example_structure():
    env_example_path = REPO_ROOT / ".env.example"
    assert env_example_path.exists(), ".env.example must exist at repository root"

    content = env_example_path.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" in content
    assert "RAG_DIR" in content
    assert "OUTPUT_DIR" in content


def test_entrypoint_script():
    entrypoint_path = REPO_ROOT / "docker" / "entrypoint.sh"
    assert entrypoint_path.exists(), "docker/entrypoint.sh must exist"

    content = entrypoint_path.read_text(encoding="utf-8")
    assert content.startswith(("#!/bin/sh", "#!/bin/bash"))
    assert 'exec "$@"' in content
