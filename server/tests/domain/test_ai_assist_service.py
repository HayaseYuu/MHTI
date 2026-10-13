"""AI 辅助的边界、安全降级和最小信息发送测试，全部使用 mock。"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from server.domain.metadata.ai_assist_service import (
    DEEPSEEK_COMPLETIONS_URL,
    AIAssistService,
)
from server.domain.system.config_service import AI_API_KEY, AI_CONFIG_KEY, ConfigService
from server.models.ai import AIConfig, AIConfigRequest, AISuggestion
from server.models.config import ProxyConfig, ProxyType
from server.models.system import SystemConfig
from server.models.tmdb import TMDBSearchResult


@pytest.fixture
def ai_config_service():
    config = AsyncMock(spec=ConfigService)
    config.get_ai_config.return_value = AIConfig(enabled=True)
    config.get_ai_api_key.return_value = "test-secret-key"
    config.has_ai_api_key.return_value = True
    config.get_system_config.return_value = SystemConfig()
    config.get_proxy_config.return_value = ProxyConfig()
    return config


@pytest.fixture
def candidates():
    return [
        TMDBSearchResult(id=123, name="芙莉莲", overview="不应发送的完整剧情"),
        TMDBSearchResult(id=-456, name="葬送的芙莉莲", metadata_source="anilist"),
    ]


def suggestion(action="identify_title", **overrides):
    data = {
        "action": action,
        "title": "葬送的芙莉莲",
        "selected_id": None,
        "confidence": 0.95,
        "reason": "名称匹配",
    }
    if action == "select_candidate":
        data.update(title=None, selected_id=123)
    return {**data, **overrides}


def envelope(data, finish_reason="stop"):
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": json.dumps(data, ensure_ascii=False)},
            }
        ]
    }


@pytest.fixture
def mocked_http():
    with patch("server.domain.metadata.ai_assist_service.httpx.AsyncClient") as constructor:
        client = AsyncMock()
        constructor.return_value.__aenter__.return_value = client
        client.post.return_value = httpx.Response(
            200,
            json=envelope(suggestion()),
            request=httpx.Request("POST", DEEPSEEK_COMPLETIONS_URL),
        )
        yield constructor, client


@pytest.mark.asyncio
async def test_identify_only_sends_basename(ai_config_service, mocked_http):
    constructor, client = mocked_http
    service = AIAssistService(ai_config_service)
    result = await service.identify_title(r"C:\private\Anime\episode.mkv", "旧标题")
    assert result.title == "葬送的芙莉莲"
    call = client.post.call_args
    assert call.args[0] == DEEPSEEK_COMPLETIONS_URL
    payload = call.kwargs["json"]
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 512
    assert payload["stream"] is False
    assert "JSON" in payload["messages"][0]["content"]
    assert json.loads(payload["messages"][1]["content"]) == {
        "action": "identify_title",
        "filename": "episode.mkv",
        "current_title": "旧标题",
    }
    assert "test-secret-key" not in json.dumps(payload)
    constructor.assert_called_once_with(timeout=15, proxy=None, follow_redirects=False)
    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_select_negative_existing_id_and_minimal_fields(
    ai_config_service, mocked_http, candidates
):
    _, client = mocked_http
    client.post.return_value = httpx.Response(
        200,
        json=envelope(suggestion("select_candidate", selected_id=-456)),
        request=httpx.Request("POST", DEEPSEEK_COMPLETIONS_URL),
    )
    result = await AIAssistService(ai_config_service).select_candidate(
        "/private/media/episode.mkv", "番名", candidates
    )
    assert result.selected_id == -456
    data = json.loads(client.post.call_args.kwargs["json"]["messages"][1]["content"])
    assert data["filename"] == "episode.mkv"
    assert set(data["candidates"][0]) == {
        "id",
        "name",
        "original_name",
        "first_air_date",
        "number_of_seasons",
        "episodes",
    }
    assert "完整剧情" not in json.dumps(data, ensure_ascii=False)
    assert "/private" not in json.dumps(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,key", [(False, "test-secret-key"), (True, None)])
async def test_disabled_or_missing_key_is_zero_network(
    ai_config_service, mocked_http, enabled, key
):
    constructor, _ = mocked_http
    ai_config_service.get_ai_config.return_value = AIConfig(enabled=enabled)
    ai_config_service.get_ai_api_key.return_value = key
    assert await AIAssistService(ai_config_service).identify_title("anime.mkv") is None
    constructor.assert_not_called()


@pytest.mark.asyncio
async def test_is_enabled_is_local_only(ai_config_service, mocked_http):
    service = AIAssistService(ai_config_service)
    assert await service.is_enabled() is True
    ai_config_service.has_ai_api_key.return_value = False
    assert await service.is_enabled() is False
    ai_config_service.get_ai_config.return_value = AIConfig()
    assert await service.is_enabled() is False
    mocked_http[0].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 21])
async def test_out_of_bounds_candidate_count_never_calls(
    ai_config_service, mocked_http, candidates, count
):
    assert (
        await AIAssistService(ai_config_service).select_candidate(
            "episode.mkv", "标题", [candidates[0]] * count
        )
        is None
    )
    mocked_http[0].assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        suggestion(confidence=0.89),
        suggestion(confidence=1.01),
        suggestion(confidence="0.95"),
        suggestion(confidence=True),
        suggestion(title=""),
        suggestion(title="行一\n行二"),
        suggestion(title="/private/media/episode"),
        suggestion(title="https://example.test/"),
        suggestion(title="A" * 161),
        suggestion(episode_number=1),
        suggestion(nfo="伪造"),
        suggestion(selected_id=123),
        suggestion(reason="A" * 241),
        suggestion("select_candidate"),
    ],
)
async def test_invalid_identify_is_rejected(ai_config_service, mocked_http, data):
    _, client = mocked_http
    client.post.return_value = httpx.Response(
        200, json=envelope(data), request=httpx.Request("POST", DEEPSEEK_COMPLETIONS_URL)
    )
    assert await AIAssistService(ai_config_service).identify_title("episode.mkv") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_id", [True, 123.0, "123", 789, None])
async def test_invalid_or_new_candidate_id_is_rejected(
    ai_config_service, mocked_http, candidates, selected_id
):
    _, client = mocked_http
    client.post.return_value = httpx.Response(
        200,
        json=envelope(suggestion("select_candidate", selected_id=selected_id)),
        request=httpx.Request("POST", DEEPSEEK_COMPLETIONS_URL),
    )
    assert (
        await AIAssistService(ai_config_service).select_candidate("episode.mkv", "番名", candidates)
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503, 302])
async def test_http_error_safe_single_attempt(ai_config_service, mocked_http, caplog, status):
    _, client = mocked_http
    client.post.return_value = httpx.Response(
        status, text="test-secret-key", request=httpx.Request("POST", DEEPSEEK_COMPLETIONS_URL)
    )
    assert await AIAssistService(ai_config_service).identify_title("episode.mkv") is None
    client.post.assert_awaited_once()
    assert "test-secret-key" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_response",
    [
        {},
        {"choices": []},
        {"choices": [None]},
        envelope(suggestion(), "length"),
        {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": {}}}]},
    ],
)
async def test_malformed_and_truncated_response_safe(ai_config_service, mocked_http, bad_response):
    _, client = mocked_http
    client.post.return_value = httpx.Response(
        200, json=bad_response, request=httpx.Request("POST", DEEPSEEK_COMPLETIONS_URL)
    )
    assert await AIAssistService(ai_config_service).identify_title("episode.mkv") is None


@pytest.mark.asyncio
async def test_timeout_capped_by_system(ai_config_service, mocked_http):
    constructor, client = mocked_http
    ai_config_service.get_ai_config.return_value = AIConfig(enabled=True, timeout_seconds=45)
    ai_config_service.get_system_config.return_value = SystemConfig(task_timeout=10)
    client.post.side_effect = httpx.ReadTimeout("test-secret-key")
    assert await AIAssistService(ai_config_service).identify_title("episode.mkv") is None
    constructor.assert_called_once_with(timeout=10, proxy=None, follow_redirects=False)


@pytest.mark.asyncio
async def test_concurrency_never_exceeds_two(ai_config_service, mocked_http):
    _, client = mocked_http
    active = maximum = 0

    async def request(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(
            200,
            json=envelope(suggestion()),
            request=httpx.Request("POST", DEEPSEEK_COMPLETIONS_URL),
        )

    client.post.side_effect = request
    service = AIAssistService(ai_config_service)
    results = await asyncio.gather(*(service.identify_title("episode.mkv") for _ in range(6)))
    assert all(results)
    assert maximum == 2


@pytest.mark.asyncio
async def test_encrypted_key_and_plain_config_are_separate(config_service):
    await config_service.save_ai_api_key("private-test-key")
    await config_service.save_ai_config(AIConfigRequest(enabled=True, api_key="must-not-persist"))
    raw = await config_service.get(AI_API_KEY)
    assert raw != "private-test-key"
    assert await config_service.get_ai_api_key() == "private-test-key"
    assert "must-not-persist" not in await config_service.get(AI_CONFIG_KEY)
    row = await config_service._repo.get_value(AI_API_KEY)
    assert row[1] is True
    assert await config_service.has_ai_api_key()
    assert await config_service.delete_ai_api_key()
    assert not await config_service.has_ai_api_key()
    assert not (await config_service.get_ai_config()).enabled


@pytest.mark.asyncio
async def test_config_defaults_and_corrupt_config(config_service):
    assert await config_service.get_ai_config() == AIConfig()
    await config_service.set(AI_CONFIG_KEY, "not JSON")
    assert await config_service.get_ai_config() == AIConfig()


def test_strict_model_cannot_enable_extra_output():
    with pytest.raises(ValidationError):
        AISuggestion(**suggestion("select_candidate", selected_id=True))


@pytest.mark.asyncio
@pytest.mark.parametrize("title", ["行一\u2028行二", "行一\u2029行二", "行一\x85行二"])
async def test_unicode_multiline_rejected(ai_config_service, mocked_http, title):
    _, client = mocked_http
    client.post.return_value = httpx.Response(
        200,
        json=envelope(suggestion(title=title)),
        request=httpx.Request("POST", DEEPSEEK_COMPLETIONS_URL),
    )
    assert await AIAssistService(ai_config_service).identify_title("episode.mkv") is None


@pytest.mark.asyncio
async def test_oversized_response_rejected(ai_config_service, mocked_http):
    _, client = mocked_http
    client.post.return_value = httpx.Response(
        200, text="x" * 65537, request=httpx.Request("POST", DEEPSEEK_COMPLETIONS_URL)
    )
    assert await AIAssistService(ai_config_service).identify_title("episode.mkv") is None


@pytest.mark.asyncio
async def test_internal_error_never_breaks_normal_scraper(ai_config_service, mocked_http, caplog):
    ai_config_service.get_ai_config.side_effect = RuntimeError("private-test-key")
    service = AIAssistService(ai_config_service)
    assert not await service.is_enabled()
    assert await service.identify_title("episode.mkv") is None
    mocked_http[0].assert_not_called()
    assert "private-test-key" not in caplog.text


@pytest.mark.asyncio
async def test_global_proxy_applies_to_ai(ai_config_service, mocked_http):
    constructor, _ = mocked_http
    ai_config_service.get_proxy_config.return_value = ProxyConfig(
        type=ProxyType.HTTP, host="127.0.0.1", port=7890
    )
    assert await AIAssistService(ai_config_service).identify_title("episode.mkv")
    constructor.assert_called_once_with(
        timeout=15, proxy="http://127.0.0.1:7890", follow_redirects=False
    )


@pytest.mark.asyncio
async def test_proxy_read_is_inside_timeout(ai_config_service, mocked_http):
    ai_config_service.get_ai_config.return_value = AIConfig(enabled=True, timeout_seconds=1)

    async def slow_proxy():
        await asyncio.sleep(1.2)
        return ProxyConfig()

    ai_config_service.get_proxy_config.side_effect = slow_proxy
    assert await AIAssistService(ai_config_service).identify_title("episode.mkv") is None
    mocked_http[0].assert_not_called()
