"""季详情只把真实 404 当作缺季，其他故障必须保留 API 错误语义。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from server.common.exceptions import ErrorCode, TMDBError, TMDBInvalidCredentialsError
from server.domain.metadata.tmdb_service import TMDBService


@pytest.fixture
def service():
    config = SimpleNamespace(
        get_language_config=AsyncMock(return_value=SimpleNamespace(primary="zh-CN"))
    )
    return TMDBService(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
async def test_non_404_http_failure_is_not_missing_season(service, status):
    service._make_api_request = AsyncMock(
        return_value=httpx.Response(status, json={"status_message": "private-key-value"})
    )
    with pytest.raises(TMDBError) as captured:
        await service.get_season_by_api(123, 1)
    assert "private-key-value" not in str(captured.value)
    if status in (401, 403):
        assert isinstance(captured.value, TMDBInvalidCredentialsError)
    elif status == 429:
        assert captured.value.code == ErrorCode.TMDB_RATE_LIMITED
        assert captured.value.status_code == 429


@pytest.mark.asyncio
async def test_only_404_returns_none(service):
    service._make_api_request = AsyncMock(return_value=httpx.Response(404))
    assert await service.get_season_by_api(123, 99) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"season_number": 1},
        {"season_number": 1, "episodes": None},
        {"season_number": "1", "episodes": []},
        {"season_number": True, "episodes": []},
        {"season_number": 2, "episodes": []},
        {"season_number": 1, "episodes": [None]},
        {"season_number": 1, "episodes": [{"name": "private-key-value"}]},
        {"season_number": 1, "episodes": [{"episode_number": True}]},
        {"season_number": 1, "episodes": [{"episode_number": -1}]},
        {"season_number": 1, "episodes": [{"episode_number": 1, "name": {"bad": 1}}]},
    ],
)
async def test_malformed_success_is_api_error_not_empty_episode_list(service, payload):
    service._make_api_request = AsyncMock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(TMDBError, match="响应格式无效") as captured:
        await service.get_season_by_api(123, 1)
    assert "private-key-value" not in str(captured.value)


@pytest.mark.asyncio
async def test_invalid_json_is_sanitized_api_error(service):
    service._make_api_request = AsyncMock(
        return_value=httpx.Response(200, text="<html>private-key-value</html>")
    )
    with pytest.raises(TMDBError, match="响应格式无效") as captured:
        await service.get_season_by_api(123, 1)
    assert "private-key-value" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpx.ReadTimeout("timeout"), httpx.ConnectError("offline")])
async def test_transport_failures_do_not_become_none(service, error):
    service._make_api_request = AsyncMock(side_effect=error)
    with pytest.raises(httpx.RequestError):
        await service.get_season_by_api(123, 1)


@pytest.mark.asyncio
async def test_valid_empty_and_recovered_season_are_distinguishable(service):
    service._make_api_request = AsyncMock(side_effect=[
        httpx.Response(503),
        httpx.Response(200, json={"season_number": 1, "episodes": []}),
        httpx.Response(200, json={
            "season_number": 1,
            "episodes": [{"episode_number": 1, "name": "Episode 1"}],
        }),
    ])
    with pytest.raises(TMDBError):
        await service.get_season_by_api(123, 1)
    empty = await service.get_season_by_api(123, 1)
    assert empty is not None and empty.episodes == []
    recovered = await service.get_season_by_api(123, 1)
    assert recovered.episodes[0].episode_number == 1
