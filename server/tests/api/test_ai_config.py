"""AI 配置接口的认证、校验与密钥不可回显测试。"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_config_service
from server.domain.system.config_service import ConfigService
from server.main import app


@pytest.fixture
def ai_client(temp_db, override_auth):
    service = ConfigService(temp_db)
    app.dependency_overrides[get_config_service] = lambda: service
    with TestClient(app) as client:
        client.config_service = service
        yield client
    app.dependency_overrides.pop(get_config_service, None)


def test_ai_default_disabled(ai_client):
    response = ai_client.get("/api/config/ai-assist")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "model": "deepseek-flash",
        "timeout_seconds": 15,
        "confidence_threshold": 0.9,
        "has_api_key": False,
    }


def test_save_keep_and_delete_encrypted_key(ai_client):
    response = ai_client.put(
        "/api/config/ai-assist", json={"enabled": True, "api_key": "private-test-key"}
    )
    assert response.status_code == 200
    assert response.json()["enabled"]
    assert response.json()["has_api_key"]
    assert "private-test-key" not in response.text
    assert "api_key" not in response.json()
    for value in (None, "", "  "):
        response = ai_client.put(
            "/api/config/ai-assist", json={"enabled": True, "api_key": value, "timeout_seconds": 12}
        )
        assert response.status_code == 200
        assert response.json()["has_api_key"]
        assert asyncio.run(ai_client.config_service.get_ai_api_key()) == "private-test-key"
    response = ai_client.get("/api/config/ai-assist")
    assert "private-test-key" not in response.text
    response = ai_client.delete("/api/config/ai-assist/api-key")
    assert response.status_code == 200
    assert not response.json()["has_api_key"]
    assert not response.json()["enabled"]
    assert asyncio.run(ai_client.config_service.get_ai_api_key()) is None


def test_enable_without_key_is_clear_error(ai_client):
    response = ai_client.put("/api/config/ai-assist", json={"enabled": True})
    assert response.status_code == 400
    assert not ai_client.get("/api/config/ai-assist").json()["enabled"]


@pytest.mark.parametrize(
    "payload",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": 46},
        {"confidence_threshold": 0.79},
        {"confidence_threshold": 1.01},
        {"model": "deepseek-chat"},
        {"base_url": "https://evil.test"},
    ],
)
def test_config_invalid_422(ai_client, payload):
    response = ai_client.put(
        "/api/config/ai-assist", json={**payload, "api_key": "private-test-key"}
    )
    assert response.status_code == 422
    assert "private-test-key" not in response.text
    assert not ai_client.get("/api/config/ai-assist").json()["has_api_key"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/config/ai-assist"),
        ("put", "/api/config/ai-assist"),
        ("delete", "/api/config/ai-assist/api-key"),
    ],
)
def test_ai_config_requires_auth(client, method, path):
    kwargs = {"json": {"api_key": "private-test-key"}} if method == "put" else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 401
    assert "private-test-key" not in response.text


@pytest.mark.parametrize(
    "api_key",
    [
        "private-test-key" * 300,
        ["private-test-key"],
        {"key": "private-test-key"},
        "private-test-key\nsecond-line",
    ],
)
def test_invalid_secret_never_echoes_in_422(ai_client, api_key, caplog):
    response = ai_client.put("/api/config/ai-assist", json={"api_key": api_key})
    assert response.status_code == 422
    assert "private-test-key" not in response.text
    assert "private-test-key" not in caplog.text
    assert "input" not in response.text
    assert "ctx" not in response.text


def test_invalid_json_never_echoes_body(ai_client, caplog):
    response = ai_client.put(
        "/api/config/ai-assist",
        content='{"api_key":"private-test-key", BROKEN}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "private-test-key" not in response.text
    assert "private-test-key" not in caplog.text


def test_invalid_body_and_extra_field_name_never_echo_secret(ai_client):
    for payload in ("private-test-key", {"private-test-key": "anything"}):
        response = ai_client.put("/api/config/ai-assist", json=payload)
        assert response.status_code == 422
        assert "private-test-key" not in response.text


def test_other_config_validation_keeps_original_shape(ai_client):
    response = ai_client.put("/api/config/proxy", json={"port": -1})
    assert response.status_code == 422
    assert "input" in response.text
