"""双源表番元数据与输出身份契约。"""

import xml.etree.ElementTree as ET
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.domain.artifacts.image_service import ImageService
from server.domain.artifacts.nfo_service import NFOService
from server.domain.metadata.anilist_service import AniListError
from server.domain.metadata.anime_metadata_service import AnimeMetadataService
from server.models.tmdb import TMDBSearchResponse, TMDBSearchResult, TMDBSeason, TMDBSeries


@pytest.fixture
def media():
    return {
        "id": 20,
        "type": "ANIME",
        "format": "TV",
        "isAdult": False,
        "title": {"native": "ナルト", "romaji": "Naruto"},
        "startDate": {"year": 2002, "month": 10, "day": 3},
        "episodes": 220,
        "description": "Anime overview",
        "genres": ["Action"],
        "coverImage": {"large": "https://s4.anilist.co/poster.jpg"},
    }


@pytest.fixture
def service():
    tmdb = MagicMock()
    tmdb.config_service.get_language_config = AsyncMock(return_value=MagicMock(primary="zh-CN"))
    tmdb.search_series_by_api = AsyncMock(
        return_value=TMDBSearchResponse(query="Naruto", total_results=0, results=[])
    )
    tmdb.get_series_by_api = AsyncMock()
    tmdb.get_season_by_api = AsyncMock(return_value=TMDBSeason(season_number=2, name="Season 2"))
    service = AnimeMetadataService(tmdb)
    service.anilist_service.search = AsyncMock(return_value=[])
    service.anilist_service.get_media = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_merge_and_nonadult_search_parameter(service, media):
    result = TMDBSearchResult(
        id=46260,
        name="Naruto",
        first_air_date=date(2002, 10, 3),
        number_of_episodes=220,
        genre_ids=[16],
    )
    service.tmdb_service.search_series_by_api.return_value = TMDBSearchResponse(
        query="Naruto", total_results=1, results=[result]
    )
    service.anilist_service.search.return_value = [media]
    response = await service.search_series_by_api("Naruto", "zh-CN")
    service.tmdb_service.search_series_by_api.assert_awaited_once_with(
        "Naruto", "zh-CN", include_adult=False
    )
    assert response.total_results == 1
    assert response.results[0].id == 46260
    assert response.results[0].anilist_id == 20
    assert response.results[0].metadata_source == "tmdb"
    assert response.results[0].overview == "Anime overview"


@pytest.mark.asyncio
@pytest.mark.parametrize("year,title", [(2003, "Naruto"), (2002, "Naruto 2"), (None, "Naruto")])
async def test_no_cross_season_or_unknown_year_merge(service, media, year, title):
    service.tmdb_service.search_series_by_api.return_value = TMDBSearchResponse(
        query="Naruto",
        total_results=1,
        results=[
            TMDBSearchResult(
                id=1, name=title, genre_ids=[16], first_air_date=date(year, 1, 1) if year else None
            )
        ],
    )
    service.anilist_service.search.return_value = [media]
    response = await service.search_series_by_api("Naruto")
    assert [r.id for r in response.results] == [1, -20]


@pytest.mark.asyncio
async def test_tmdb_failed_or_not_configured_falls_back(service, media):
    service.tmdb_service.search_series_by_api.side_effect = RuntimeError("No API token")
    service.anilist_service.search.return_value = [media]
    response = await service.search_series_by_api("Naruto")
    assert response.results[0].id == -20
    service.anilist_service.get_media.return_value = media
    series = await service.get_series_by_api(-20)
    assert series.number_of_episodes == 220
    season = await service.get_season_by_api(-20, 1)
    assert len(season.episodes) == 220
    assert await service.get_season_by_api(-20, 2) is None
    service.tmdb_service.get_series_by_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_anilist_failure_keeps_animation_tmdb(service):
    service.anilist_service.search.side_effect = AniListError("rate limit")
    service.tmdb_service.search_series_by_api.return_value = TMDBSearchResponse(
        query="Naruto",
        total_results=2,
        results=[
            TMDBSearchResult(id=1, name="Anime", genre_ids=[16]),
            TMDBSearchResult(id=2, name="Live action", genre_ids=[18]),
        ],
    )
    response = await service.search_series_by_api("Naruto")
    assert [r.id for r in response.results] == [1]


@pytest.mark.asyncio
async def test_both_sources_fail_report_error(service):
    service.tmdb_service.search_series_by_api.side_effect = RuntimeError("TMDB down")
    service.anilist_service.search.side_effect = AniListError("AniList down")
    with pytest.raises(AniListError):
        await service.search_series_by_api("Naruto")


@pytest.mark.asyncio
async def test_tmdb_adult_never_leaks(service):
    service.tmdb_service.search_series_by_api.return_value = TMDBSearchResponse(
        query="test",
        total_results=1,
        results=[TMDBSearchResult(id=1, name="adult", adult=True, genre_ids=[16])],
    )
    assert (await service.search_series_by_api("test")).results == []
    service.tmdb_service.get_series_by_api.return_value = TMDBSeries(id=1, name="adult", adult=True)
    assert await service.get_series_by_api(1) is None


@pytest.mark.asyncio
async def test_details_merge_retains_tmdb_seasons(service, media):
    original = TMDBSeries(
        id=1,
        name="Naruto",
        genre_ids=[16],
        first_air_date=date(2002, 10, 3),
        overview="Chinese overview",
        number_of_seasons=5,
        number_of_episodes=220,
    )
    service.tmdb_service.get_series_by_api.return_value = original
    service.anilist_service.search.return_value = [media]
    series = await service.get_series_by_api(1)
    assert series.overview == "Chinese overview" and series.anilist_id == 20
    assert series.number_of_seasons == 5
    assert (await service.get_season_by_api(1, 2)).season_number == 2
    service.tmdb_service.get_season_by_api.assert_awaited_once_with(1, 2, "zh-CN")
    assert original.anilist_id is None


@pytest.mark.asyncio
async def test_details_anilist_failure_keeps_tmdb(service):
    service.tmdb_service.get_series_by_api.return_value = TMDBSeries(
        id=1, name="Anime", genre_ids=[16]
    )
    service.anilist_service.search.side_effect = AniListError("down")
    assert (await service.get_series_by_api(1)).id == 1


@pytest.mark.asyncio
async def test_live_action_details_rejected(service):
    service.tmdb_service.get_series_by_api.return_value = TMDBSeries(
        id=1, name="Drama", genre_ids=[18]
    )
    assert await service.get_series_by_api(1) is None


def test_nfo_independent_anilist_never_writes_negative_tmdb(service, media):
    nfo = NFOService()
    series = service.anilist_service.to_series(media)
    root = ET.fromstring(nfo.generate_tvshow_nfo(nfo.tvshow_from_tmdb(series)))
    assert root.find("tmdbid") is None
    assert root.find("uniqueid[@type='tmdb']") is None
    assert root.find("episodeguide") is None
    assert root.find("uniqueid[@type='anilist']").text == "20"


def test_nfo_merged_retains_both_real_ids():
    nfo = NFOService()
    data = nfo.tvshow_from_tmdb(TMDBSeries(id=1, name="Anime", anilist_id=20))
    root = ET.fromstring(nfo.generate_tvshow_nfo(data))
    assert root.find("uniqueid[@type='tmdb']").text == "1"
    assert root.find("uniqueid[@type='anilist']").text == "20"


@pytest.mark.parametrize(
    "url",
    [
        "https://s4.anilist.co/file/anilistcdn/poster.jpg",
        "https://image.tmdb.org/t/p/w500/poster.jpg",
    ],
)
def test_trusted_https_images(url):
    assert ImageService(MagicMock()).get_full_image_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://s4.anilist.co/a.jpg",
        "https://evil.test/a.jpg",
        "https://s4.anilist.co.evil.test/a.jpg",
        "https://user@s4.anilist.co/a.jpg",
        "https://s4.anilist.co:8888/a.jpg",
        "//s4.anilist.co/a.jpg",
        "file:///etc/passwd",
    ],
)
def test_untrusted_image_urls_rejected(url):
    assert ImageService(MagicMock()).get_full_image_url(url) is None


@pytest.mark.asyncio
async def test_ambiguous_same_year_candidates_do_not_merge(service, media):
    service.tmdb_service.search_series_by_api.return_value = TMDBSearchResponse(
        query="Naruto",
        total_results=2,
        results=[
            TMDBSearchResult(id=n, name="Naruto", genre_ids=[16], first_air_date=date(2002, 10, 3))
            for n in (1, 2)
        ],
    )
    service.anilist_service.search.return_value = [media]
    response = await service.search_series_by_api("Naruto")
    assert [r.id for r in response.results] == [1, 2, -20]
    assert all(r.anilist_id is None for r in response.results[:2])


@pytest.mark.asyncio
async def test_default_language_respects_config(service, media):
    service.config_service.get_language_config.return_value = MagicMock(primary="en-US")
    media["title"]["english"] = "Naruto English"
    service.tmdb_service.search_series_by_api.side_effect = RuntimeError("No API token")
    service.anilist_service.search.return_value = [media]
    assert (await service.search_series_by_api("Naruto")).results[0].name == "Naruto English"
    service.anilist_service.get_media.return_value = media
    assert (await service.get_series_by_api(-20)).name == "Naruto English"


@pytest.fixture
def api_client(service):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.api.deps import get_tmdb_service, require_auth
    from server.api.middleware import setup_exception_handlers
    from server.api.v1.tmdb import router

    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_tmdb_service] = lambda: service.tmdb_service
    return TestClient(app)


def test_http_search_without_tmdb_credentials_falls_back(api_client, service, media):
    from unittest.mock import patch

    from server.common.exceptions import TMDBNotConfiguredError

    service.tmdb_service.search_series_by_api.side_effect = TMDBNotConfiguredError("API Token")
    with patch(
        "server.domain.metadata.anilist_service.AniListService.search",
        new=AsyncMock(return_value=[media]),
    ):
        response = api_client.get("/api/tmdb/search", params={"q": "Naruto", "r18": False})
    assert response.status_code == 200
    data = response.json()["results"][0]
    assert data["id"] == -20 and data["anilist_id"] == 20
    assert data["metadata_source"] == "anilist"


def test_http_both_sources_down_returns_explainable_error(api_client, service):
    from unittest.mock import patch

    from server.common.exceptions import TMDBNotConfiguredError

    service.tmdb_service.search_series_by_api.side_effect = TMDBNotConfiguredError("API Token")
    with patch(
        "server.domain.metadata.anilist_service.AniListService.search",
        new=AsyncMock(side_effect=AniListError("AniList 连接失败")),
    ):
        response = api_client.get("/api/tmdb/search", params={"q": "Naruto", "r18": False})
    assert response.status_code == 502
    assert response.json()["error"]["details"]["source"] == "anilist"


def test_http_r18_remains_tmdb_only(api_client, service):
    from unittest.mock import patch

    service.tmdb_service.search_series_by_api.return_value = TMDBSearchResponse(
        query="adult",
        total_results=2,
        results=[
            TMDBSearchResult(id=1, name="adult", adult=True),
            TMDBSearchResult(id=2, name="normal", adult=False),
        ],
    )
    with patch(
        "server.domain.metadata.anilist_service.AniListService.search", new=AsyncMock()
    ) as search:
        response = api_client.get("/api/tmdb/search", params={"q": "adult", "r18": True})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["results"]] == [1]
    search.assert_not_awaited()
