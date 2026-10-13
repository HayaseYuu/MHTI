"""数据源故障与名称未匹配必须分开，禁止为普通网络故障调用 AI。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from server.common.exceptions import TMDBError, TMDBNotConfiguredError
from server.domain.metadata.anilist_service import AniListError
from server.domain.metadata.anime_metadata_service import AnimeMetadataService
from server.domain.metadata.tmdb_service import TMDBService
from server.models.tmdb import TMDBSearchResponse


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 502])
async def test_http_failure_is_not_empty_search(config_service, status, monkeypatch):
    service = TMDBService(config_service)
    monkeypatch.setattr(
        service, "_make_api_request", AsyncMock(return_value=httpx.Response(status))
    )
    with pytest.raises(TMDBError):
        await service.search_series_by_api("Anime", language="zh-CN")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["tmdb", "anilist", "not_configured"])
async def test_partial_failures_cannot_be_used_for_ai_title_guess(config_service, failure):
    tmdb = SimpleNamespace(
        config_service=config_service,
        search_series_by_api=AsyncMock(
            return_value=TMDBSearchResponse(query="Anime", total_results=0, results=[])
        ),
    )
    service = AnimeMetadataService(tmdb)
    service.anilist_service.search = AsyncMock(return_value=[])
    if failure == "anilist":
        service.anilist_service.search.side_effect = AniListError("unavailable")
    elif failure == "not_configured":
        tmdb.search_series_by_api.side_effect = TMDBNotConfiguredError("API Token")
    else:
        tmdb.search_series_by_api.side_effect = TMDBError("unavailable")
    response = await service.search_series_by_api("Anime", "zh-CN")
    assert response.search_complete is (failure == "not_configured")
