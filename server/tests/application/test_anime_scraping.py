"""表番/R18 任务隔离与完整整理流程回归测试（不访问外部网络）。"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from server.application.scraping.config_resolver import ScraperConfigResolver
from server.domain.parsing.parser_service import ParserService
from server.models.manual_job import ManualJobAdvancedSettings
from server.models.organize import OrganizeMode
from server.models.scraper import ScrapeByIdRequest, ScrapeRequest, ScrapeStatus
from server.models.tmdb import TMDBSearchResponse, TMDBSearchResult, TMDBSeries
from server.tests.application.test_scraper_service import (
    FakeTMDB,
    _build_service,
    _patch_tail,
    _series,
)


def _anime() -> TMDBSeries:
    return _series().model_copy(update={
        "id": -7, "adult": False, "metadata_source": "anilist", "anilist_id": 7,
    })


def _provider(series, results=None):
    return FakeTMDB(series=series, search_results=results or [
        TMDBSearchResult(id=series.id, name=series.name, adult=series.adult,
                         metadata_source=series.metadata_source),
    ])


def _service(temp_db, monkeypatch, adult_series=None, anime_series=None):
    adult_provider = _provider(adult_series or _series())
    anime_provider = _provider(anime_series or _anime())
    service = _build_service(temp_db, adult_provider, parser=ParserService())
    monkeypatch.setattr(service, "anime_metadata_service", anime_provider)
    _patch_tail(monkeypatch, service)
    return service, adult_provider, anime_provider


@pytest.mark.asyncio
@pytest.mark.parametrize("r18, expected_id", [(False, -7), (True, 123)])
async def test_complete_scrape_in_each_mode(temp_db, tmp_path, monkeypatch, r18, expected_id):
    service, adult, anime = _service(temp_db, monkeypatch)
    source = tmp_path / "Test.Show.S01E01.mp4"
    source.write_bytes(b"video")
    request = ScrapeRequest(file_path=str(source), output_dir=str(tmp_path / "library"),
                            link_mode=OrganizeMode.COPY,
                            advanced_settings=ManualJobAdvancedSettings(r18=r18))
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.SUCCESS
    assert result.selected_id == expected_id
    assert Path(result.dest_path).read_bytes() == b"video"
    assert Path(result.nfo_path).exists()
    (anime if r18 else adult).search_series_by_api.assert_not_awaited()
    messages = [log.message for step in result.scrape_logs for log in step.logs]
    assert any(("R18" if r18 else "表番") in message for message in messages)


@pytest.mark.asyncio
async def test_default_mode_is_anime(temp_db, tmp_path, monkeypatch):
    service, adult, anime = _service(temp_db, monkeypatch)
    source = tmp_path / "Test.Show.S01E01.mp4"
    source.write_bytes(b"video")
    result = await service.scrape_file(ScrapeRequest(file_path=str(source), auto_select=False))
    assert result.status == ScrapeStatus.NEED_SELECTION
    assert result.search_results[0].id == -7
    adult.search_series_by_api.assert_not_awaited()
    # AniList 搜索已经包含季集数量，不重复请求详情。
    anime.get_series_by_api.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("r18", [False, True])
async def test_search_results_cannot_cross_content_mode(temp_db, tmp_path, monkeypatch, r18):
    service, adult, anime = _service(temp_db, monkeypatch)
    response = TMDBSearchResponse(query="test", total_results=2, results=[
        TMDBSearchResult(id=123, name="Adult", adult=True),
        TMDBSearchResult(id=-7, name="Anime", adult=False, metadata_source="anilist"),
    ])
    (adult if r18 else anime).search_series_by_api.return_value = response
    source = tmp_path / "Test.Show.S01E01.mp4"
    source.write_bytes(b"video")
    result = await service.scrape_file(ScrapeRequest(file_path=str(source), auto_select=False,
        advanced_settings=ManualJobAdvancedSettings(r18=r18)))
    assert result.status == ScrapeStatus.NEED_SELECTION
    assert len(result.search_results) == 1
    assert result.search_results[0].adult == r18


@pytest.mark.asyncio
@pytest.mark.parametrize("r18, selected_id", [(False, 123), (True, 123)])
async def test_manual_id_rejects_opposite_mode(temp_db, tmp_path, monkeypatch, r18, selected_id):
    service, adult, anime = _service(temp_db, monkeypatch)
    (adult if r18 else anime).get_series_by_api.return_value = (
        _anime() if r18 else _series()
    )
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    result = await service.scrape_by_id(ScrapeByIdRequest(file_path=str(source),
        tmdb_id=selected_id, season=1, episode=1,
        advanced_settings=ManualJobAdvancedSettings(r18=r18)))
    assert result.status == ScrapeStatus.API_FAILED
    assert "模式不一致" in result.message
    assert source.exists()
    (adult if r18 else anime).get_season_by_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_r18_negative_id_rejected_before_tmdb_request(temp_db, tmp_path, monkeypatch):
    service, adult, anime = _service(temp_db, monkeypatch)
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    result = await service.scrape_by_id(ScrapeByIdRequest(file_path=str(source),
        tmdb_id=-7, season=1, episode=1,
        advanced_settings=ManualJobAdvancedSettings(r18=True)))
    assert result.status == ScrapeStatus.API_FAILED
    adult.get_series_by_api.assert_not_awaited()
    anime.get_series_by_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_anilist_manual_retry_complete_tail(temp_db, tmp_path, monkeypatch):
    service, adult, anime = _service(temp_db, monkeypatch)
    source = tmp_path / "input.mp4"
    source.write_bytes(b"video")
    result = await service.scrape_by_id(ScrapeByIdRequest(file_path=str(source),
        tmdb_id=-7, season=1, episode=1, link_mode=OrganizeMode.COPY,
        output_dir=str(tmp_path / "library"),
        advanced_settings=ManualJobAdvancedSettings(r18=False)))
    assert result.status == ScrapeStatus.SUCCESS
    assert result.series_info.anilist_id == 7
    assert Path(result.dest_path).exists()
    adult.get_series_by_api.assert_not_awaited()
    anime.get_season_by_api.assert_awaited_once_with(-7, 1)


@pytest.mark.asyncio
async def test_anilist_sequel_season_requires_confirmation(temp_db, tmp_path, monkeypatch):
    service, _, anime = _service(temp_db, monkeypatch)
    anime.get_season_by_api.return_value = None
    source = tmp_path / "Test.Show.S02E01.mp4"
    source.write_bytes(b"video")
    result = await service.scrape_file(ScrapeRequest(file_path=str(source)))
    assert result.status == ScrapeStatus.NEED_SEASON_EPISODE
    assert result.parsed_season == 2
    assert source.exists()
    assert service._auto_correct_season(2, _anime()) == (2, None)


@pytest.mark.asyncio
async def test_concurrent_modes_do_not_share_provider_state(temp_db, tmp_path, monkeypatch):
    service, adult, anime = _service(temp_db, monkeypatch)
    ready = asyncio.Event()

    async def adult_search(query):
        ready.set()
        await asyncio.sleep(0.01)
        return TMDBSearchResponse(query=query, total_results=1,
                                 results=[TMDBSearchResult(id=123, name="Adult", adult=True)])

    async def anime_search(query):
        await ready.wait()
        return TMDBSearchResponse(query=query, total_results=1,
                                 results=[TMDBSearchResult(id=-7, name="Anime", adult=False)])

    adult.search_series_by_api.side_effect = adult_search
    anime.search_series_by_api.side_effect = anime_search
    source = tmp_path / "Test.Show.S01E01.mp4"
    source.write_bytes(b"video")
    results = await asyncio.gather(*[
        service.scrape_file(ScrapeRequest(file_path=str(source), auto_select=False,
            advanced_settings=ManualJobAdvancedSettings(r18=mode)))
        for mode in (True, False)
    ])
    assert [result.search_results[0].id for result in results] == [123, -7]
    adult.get_series_by_api.assert_awaited_once_with(123)
    # AniList 搜索已经包含季集数量，不重复请求详情。
    anime.get_series_by_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_config_anime_without_credentials_and_r18_without_cookie():
    tmdb = AsyncMock()
    resolver = ScraperConfigResolver(AsyncMock(), tmdb)
    assert await resolver.check_config(False) == (True, None)
    await resolver.ensure_config_ready(False)
    tmdb.get_api_token_status.assert_not_awaited()
    tmdb.get_api_token_status.return_value.is_configured = True
    tmdb.get_api_token_status.return_value.is_valid = True
    assert await resolver.check_config(True) == (True, None)
    await resolver.ensure_config_ready(True)
    tmdb.get_cookie_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_metadata_outage_returns_failed_result(temp_db, tmp_path, monkeypatch):
    from server.domain.metadata.anilist_service import AniListError

    service, _, anime = _service(temp_db, monkeypatch)
    anime.search_series_by_api.side_effect = AniListError("AniList 请求超时")
    source = tmp_path / "Test.Show.S01E01.mp4"
    source.write_bytes(b"video")
    result = await service.scrape_file(ScrapeRequest(file_path=str(source)))
    assert result.status == ScrapeStatus.SEARCH_FAILED
    assert "AniList 请求超时" in result.message


@pytest.mark.asyncio
async def test_anime_api_routes_use_same_provider_and_guard_mode(monkeypatch):
    from server.api.v1 import tmdb as api
    from server.common.exceptions import TMDBNotFoundError

    adult = _provider(_series())
    anime = _provider(_anime())
    monkeypatch.setattr(api, "AnimeMetadataService", lambda tmdb: anime)
    search = await api.search_tv(q="Anime", language="zh-CN", r18=False, tmdb_service=adult)
    assert search.results[0].id == -7
    series = await api.get_series(tmdb_id=-7, language="zh-CN", include_episodes=True,
                                  r18=False, tmdb_service=adult)
    assert series.seasons[0].episodes[0].episode_number == 1
    season = await api.get_season(tmdb_id=-7, season_number=1, language="zh-CN",
                                  r18=False, tmdb_service=adult)
    assert season.season_number == 1
    adult.get_series_by_api.assert_not_awaited()
    with pytest.raises(TMDBNotFoundError):
        await api.get_series(tmdb_id=-7, language="zh-CN", include_episodes=False,
                             r18=True, tmdb_service=adult)
    with pytest.raises(TMDBNotFoundError):
        await api.get_season(tmdb_id=-7, season_number=1, language="zh-CN",
                             r18=True, tmdb_service=adult)
    adult.get_series_by_api.assert_not_awaited()
    anime.get_series_by_api.return_value = _series()
    with pytest.raises(TMDBNotFoundError):
        await api.get_season(tmdb_id=123, season_number=1, language="zh-CN",
                             r18=False, tmdb_service=adult)


@pytest.mark.asyncio
async def test_r18_api_search_filters_nonadult_results():
    from server.api.v1 import tmdb as api

    adult = _provider(_series(), [TMDBSearchResult(id=123, name="Adult", adult=True),
                                 TMDBSearchResult(id=456, name="Anime", adult=False)])
    response = await api.search_tv(q="Test", language="zh-CN", r18=True, tmdb_service=adult)
    assert [item.id for item in response.results] == [123]
    assert response.total_results == 1
    adult.search_series_by_api.assert_awaited_once_with("Test", "zh-CN", include_adult=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, True])
async def test_batch_preserves_content_mode(temp_db, tmp_path, monkeypatch, dry_run):
    from server.models.scraper import BatchScrapeRequest, ScrapePreview, ScrapeResult

    service, _, _ = _service(temp_db, monkeypatch)
    service.preview = AsyncMock(return_value=ScrapePreview(file_path="episode.mp4"))
    service.scrape_file = AsyncMock(return_value=ScrapeResult(file_path="episode.mp4",
                                                            status=ScrapeStatus.SUCCESS))
    settings = ManualJobAdvancedSettings(r18=True)
    await service.batch_scrape(BatchScrapeRequest(file_paths=["episode.mp4"], dry_run=dry_run,
                                                advanced_settings=settings))
    if dry_run:
        service.preview.assert_awaited_once_with("episode.mp4", r18=True)
    else:
        assert service.scrape_file.call_args.args[0].advanced_settings.r18 is True
