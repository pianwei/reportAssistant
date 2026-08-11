from app.config import Settings


ENV_NAMES = (
    "DATA_DIR",
    "DATABASE_PATH",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_TIMEOUT_SECONDS",
)


def test_settings_load_env_file(tmp_path, monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_BASE_URL=https://model.example/v1",
                "LLM_MODEL=test-model",
                "LLM_API_KEY=test-secret",
                "LLM_TIMEOUT_SECONDS=45",
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings.from_env(env_file)
    assert settings.llm_base_url == "https://model.example/v1"
    assert settings.llm_model == "test-model"
    assert settings.llm_api_key == "test-secret"
    assert settings.llm_timeout_seconds == 45


def test_process_environment_overrides_env_file(tmp_path, monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setenv("LLM_MODEL", "process-model")
    settings = Settings.from_env(env_file)
    assert settings.llm_model == "process-model"
