"""Environment defaults are captured when a configuration is constructed."""

from dotenv import load_dotenv

from raganything.config import RAGAnythingConfig


def test_environment_loaded_after_import(tmp_path, monkeypatch):
    monkeypatch.delenv("MINERU_PARSE_METHOD", raising=False)
    values = {
        "WORKING_DIR": "./loaded-storage",
        "PARSER": "docling",
        "MAX_CONCURRENT_FILES": "4",
        "ENABLE_IMAGE_PROCESSING": "false",
    }
    for key in values:
        monkeypatch.setenv(key, "")
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    load_dotenv(env_file, override=True)

    config = RAGAnythingConfig()
    assert config.working_dir == "./loaded-storage"
    assert config.parser == "docling"
    assert config.max_concurrent_files == 4
    assert config.enable_image_processing is False


def test_each_configuration_captures_current_environment(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_FILES", "2")
    first = RAGAnythingConfig()
    monkeypatch.setenv("MAX_CONCURRENT_FILES", "3")
    second = RAGAnythingConfig()
    explicit = RAGAnythingConfig(max_concurrent_files=7)
    assert first.max_concurrent_files == 2
    assert second.max_concurrent_files == 3
    assert explicit.max_concurrent_files == 7
