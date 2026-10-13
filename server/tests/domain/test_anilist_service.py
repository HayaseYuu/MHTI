"""AniList 客户端：内容边界、HTTP/GraphQL 错误与不完整日期。"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.domain.metadata.anilist_service import MAX_EPISODES, AniListError, AniListService
from server.models.config import ProxyConfig
from server.models.system import SystemConfig


@pytest.fixture
def service():
    config = MagicMock()
    config.get_system_config = AsyncMock(return_value=SystemConfig(task_timeout=17))
    config.get_proxy_config = AsyncMock(return_value=ProxyConfig())
    return AniListService(config)


@pytest.fixture
def media():
    return {
        "id": 20,
        "type": "ANIME",
        "format": "TV",
        "isAdult": False,
        "title": {"native": "ナルト", "romaji": "Naruto", "english": "Naruto"},
        "startDate": {"year": 2002, "month": 10, "day": 3},
        "episodes": 220,
        "averageScore": 80,
        "description": "<b>Story</b> &amp; heroes",
        "coverImage": {"large": "https://s4.anilist.co/poster.jpg"},
    }


@pytest.mark.asyncio
async def test_request_configuration_and_query(service, media):
    response = httpx.Response(
        200,
        json={"data": {"Page": {"media": [media]}}},
        request=httpx.Request("POST", "https://graphql.anilist.co"),
    )
    with patch("httpx.AsyncClient") as client:
        instance = AsyncMock()
        instance.post.return_value = response
        client.return_value.__aenter__.return_value = instance
        result = await service.search("Naruto")
        assert result == [media]
        client.assert_called_once_with(timeout=17.0, proxy=None)
        args = instance.post.call_args
        assert args.kwargs["json"]["variables"] == {"search": "Naruto", "perPage": 20}
        assert "isAdult: false" in args.kwargs["json"]["query"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload",
    [
        (429, {}),
        (503, {}),
        (200, {"errors": [{"message": "error"}]}),
        (200, {"data": None}),
        (200, []),
    ],
)
async def test_request_errors_no_retry(service, status, payload):
    response = httpx.Response(
        status, json=payload, request=httpx.Request("POST", "https://graphql.anilist.co")
    )
    with patch("httpx.AsyncClient") as client:
        instance = AsyncMock()
        instance.post.return_value = response
        client.return_value.__aenter__.return_value = instance
        with pytest.raises(AniListError):
            await service.search("test")
        assert instance.post.await_count == 1


@pytest.mark.asyncio
async def test_timeout(service):
    with patch("httpx.AsyncClient") as client:
        instance = AsyncMock()
        instance.post.side_effect = httpx.TimeoutException("timeout")
        client.return_value.__aenter__.return_value = instance
        with pytest.raises(AniListError, match="超时"):
            await service.get_media(20)


@pytest.mark.asyncio
async def test_search_filters_adult_manga_unknown_and_movies(service, media):
    service._request = AsyncMock(
        return_value={
            "Page": {
                "media": [
                    media,
                    {**media, "isAdult": True},
                    {**media, "isAdult": None},
                    {**media, "type": "MANGA"},
                    {**media, "format": "MOVIE"},
                    {**media, "id": -1},
                ]
            }
        }
    )
    assert await service.search("test") == [media]


@pytest.mark.asyncio
async def test_detail_filters_adult(service, media):
    service._request = AsyncMock(return_value={"Media": {**media, "isAdult": True}})
    assert await service.get_media(20) is None


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"year": 2020},
        {"year": 2020, "month": 2, "day": 31},
        {"year": None, "month": 1, "day": 1},
    ],
)
def test_incomplete_date_not_invented(service, value):
    assert service.parse_date(value) is None


def test_convert_identity_rating_html_and_placeholders(service, media):
    series = service.to_series(media)
    assert series.id == -20 and series.anilist_id == 20
    assert series.metadata_source == "anilist" and series.adult is False
    assert series.vote_average == 8 and series.overview == "Story & heroes"
    assert service.to_series(media, "en-US").name == "Naruto"
    episodes = service.to_season(media).episodes
    assert len(episodes) == 220
    assert episodes[0].name == "Episode 1" and episodes[-1].episode_number == 220
    assert all(ep.air_date is None and ep.overview is None for ep in episodes)


@pytest.mark.parametrize("count", [None, 0, -1, MAX_EPISODES + 1])
def test_unknown_or_out_of_bounds_episode_count(service, media, count):
    media["episodes"] = count
    media["startDate"] = {"year": 2002}
    series = service.to_series(media)
    assert series.first_air_date is None and series.number_of_episodes is None
    assert service.to_season(media).episodes == []
