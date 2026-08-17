from app.config import Settings


ENV_NAMES = (
    "DATA_DIR",
    "DATABASE_URL",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_TIMEOUT_SECONDS",
    "LLM_TLS_VERIFY",
    "LLM_CA_CERT_PATH",
    "LLM_AUTH_HEADER",
    "LLM_AUTH_SCHEME",
    "MODEL_PROFILE_FROM_DATABASE",
)


def test_settings_load_env_file(tmp_path, monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_BASE_URL=https://model.example/v1",
                "DATABASE_URL=mysql://app:secret@mysql.example:3306/due_diligence",
                "LLM_MODEL=test-model",
                "LLM_API_KEY=test-secret",
                "LLM_TIMEOUT_SECONDS=45",
                "LLM_TLS_VERIFY=false",
                "LLM_CA_CERT_PATH=/certs/bank.pem",
                "LLM_AUTH_HEADER=X-API-Key",
                "LLM_AUTH_SCHEME=",
                "MODEL_PROFILE_FROM_DATABASE=false",
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings.from_env(env_file)
    assert settings.llm_base_url == "https://model.example/v1"
    assert settings.database_url == "mysql://app:secret@mysql.example:3306/due_diligence"
    assert settings.llm_model == "test-model"
    assert settings.llm_api_key == "test-secret"
    assert settings.llm_timeout_seconds == 45
    assert settings.llm_tls_verify is False
    assert settings.llm_ca_cert_path == "/certs/bank.pem"
    assert settings.llm_auth_header == "X-API-Key"
    assert settings.llm_auth_scheme == ""
    assert settings.model_profile_from_database is False


def test_process_environment_overrides_env_file(tmp_path, monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setenv("LLM_MODEL", "process-model")
    settings = Settings.from_env(env_file)
    assert settings.llm_model == "process-model"
