"""季详情故障不生成缺集冲突、不调用 AI、不触碰文件，恢复后可重试。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from server.common.exceptions import TMDBConnectionError
from server.domain.metadata.tmdb_service import TMDBService
from server.models.manual_job import ManualJobAdvancedSettings
from server.models.organize import OrganizeMode
from server.models.parser import ParsedInfo
from server.models.scraper import ScrapeByIdRequest, ScrapeRequest, ScrapeStatus
from server.models.tmdb import TMDBSeason
from server.tests.application.test_anime_scraping import _service


def _case(temp_db, tmp_path, monkeypatch, r18, entrypoint):
    service, adult, anime = _service(temp_db, monkeypatch)
    provider = adult if r18 else anime
    selected_id = 123 if r18 else -7
    source = tmp_path / "Test.Show.S01E01.mp4"
    source.write_bytes(b"video")
    kwargs = {
        "file_path": str(source),
        "output_dir": str(tmp_path / "library"),
        "link_mode": OrganizeMode.COPY,
        "advanced_settings": ManualJobAdvancedSettings(r18=r18),
    }
    if entrypoint == "by_id":
        request = ScrapeByIdRequest(**kwargs, tmdb_id=selected_id, season=1, episode=1)
        execute = service.scrape_by_id
    else:
        request = ScrapeRequest(**kwargs)
        execute = service.scrape_file
    service.ai_assist_service = SimpleNamespace(
        is_enabled=AsyncMock(return_value=True),
        identify_title=AsyncMock(),
        select_candidate=AsyncMock(),
    )
    service._move_and_finalize = AsyncMock(wraps=service._move_and_finalize)
    service._generate_episode_nfo = Mock(wraps=service._generate_episode_nfo)
    return service, provider, selected_id, source, execute, request


def _assert_untouched(service, source, result):
    assert source.read_bytes() == b"video"
    assert not (source.parent / "library").exists()
    assert result.dest_path is None and result.nfo_path is None
    service._move_and_finalize.assert_not_awaited()
    service._generate_episode_nfo.assert_not_called()
    service._check_emby_conflict.assert_not_awaited()
    service.ai_assist_service.is_enabled.assert_not_awaited()
    service.ai_assist_service.identify_title.assert_not_awaited()
    service.ai_assist_service.select_candidate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["normal", "by_id"])
@pytest.mark.parametrize("r18", [False, True])
@pytest.mark.parametrize("failure", [401, 429, 503, "timeout", "connect", "malformed"])
async def test_season_api_failures_preserve_match_without_file_or_ai_actions(
    temp_db, tmp_path, monkeypatch, entrypoint, r18, failure
):
    service, provider, selected_id, source, execute, request = _case(
        temp_db, tmp_path, monkeypatch, r18, entrypoint
    )
    tmdb = TMDBService(SimpleNamespace(
        get_language_config=AsyncMock(return_value=SimpleNamespace(primary="zh-CN"))
    ))
    if failure == "timeout":
        tmdb._make_api_request = AsyncMock(side_effect=httpx.ReadTimeout("private-key-value"))
    elif failure == "connect":
        tmdb._make_api_request = AsyncMock(
            side_effect=TMDBConnectionError("https://user:private-key-value@host/")
        )
    elif failure == "malformed":
        tmdb._make_api_request = AsyncMock(return_value=httpx.Response(200, json={}))
    else:
        tmdb._make_api_request = AsyncMock(return_value=httpx.Response(failure))
    provider.get_season_by_api = tmdb.get_season_by_api
    result = await execute(request)
    assert result.status == ScrapeStatus.API_FAILED
    assert (result.selected_id, result.parsed_season, result.parsed_episode) == (selected_id, 1, 1)
    assert "不存在" not in result.message and "重试" in result.message
    assert "private-key-value" not in result.model_dump_json()
    _assert_untouched(service, source, result)


@pytest.mark.asyncio
@pytest.mark.parametrize("r18", [False, True])
@pytest.mark.parametrize("total_episodes, expected_episode", [(1, 1), (12, None)])
async def test_missing_episode_inference_does_not_swallow_season_transport_failure(
    temp_db, tmp_path, monkeypatch, r18, total_episodes, expected_episode
):
    service, provider, selected_id, source, execute, request = _case(
        temp_db, tmp_path, monkeypatch, r18, "normal"
    )
    provider.get_series_by_api.return_value.number_of_episodes = total_episodes
    service.parser_service = Mock(parse=Mock(return_value=ParsedInfo(
        original_filename=source.name, series_name="Test Show"
    )))
    provider.get_season_by_api.side_effect = httpx.ReadTimeout("private-key-value")
    result = await execute(request)
    assert result.status == ScrapeStatus.API_FAILED
    assert (result.selected_id, result.parsed_season, result.parsed_episode) == (
        selected_id, 1, expected_episode
    )
    assert "private-key-value" not in result.model_dump_json()
    _assert_untouched(service, source, result)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["normal", "by_id"])
@pytest.mark.parametrize("r18", [False, True])
@pytest.mark.parametrize(
    "missing", [None, TMDBSeason(season_number=1, name="Season 1", episodes=[])]
)
async def test_real_missing_season_or_episode_still_needs_confirmation(
    temp_db, tmp_path, monkeypatch, entrypoint, r18, missing
):
    service, provider, selected_id, source, execute, request = _case(
        temp_db, tmp_path, monkeypatch, r18, entrypoint
    )
    provider.get_season_by_api.return_value = missing
    result = await execute(request)
    assert result.status == ScrapeStatus.NEED_SEASON_EPISODE
    assert (result.selected_id, result.parsed_season, result.parsed_episode) == (selected_id, 1, 1)
    _assert_untouched(service, source, result)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["normal", "by_id"])
@pytest.mark.parametrize("r18", [False, True])
async def test_season_api_recovery_retries_original_match_and_finishes(
    temp_db, tmp_path, monkeypatch, entrypoint, r18
):
    service, provider, selected_id, source, execute, request = _case(
        temp_db, tmp_path, monkeypatch, r18, entrypoint
    )
    valid_season = provider.get_season_by_api.return_value
    provider.get_season_by_api.side_effect = [httpx.ReadTimeout("timeout"), valid_season]
    failed = await execute(request)
    assert failed.status == ScrapeStatus.API_FAILED
    _assert_untouched(service, source, failed)
    retried = await execute(request)
    assert retried.status == ScrapeStatus.SUCCESS
    assert (retried.selected_id, retried.parsed_season, retried.parsed_episode) == (
        selected_id, 1, 1
    )
    assert Path(retried.dest_path).read_bytes() == b"video"
    assert Path(retried.nfo_path).exists()


@pytest.mark.asyncio
async def test_unknown_anilist_episode_count_never_creates_episode_numbers(
    temp_db, tmp_path, monkeypatch
):
    service, provider, _, source, execute, request = _case(
        temp_db, tmp_path, monkeypatch, False, "normal"
    )
    provider.get_series_by_api.return_value.number_of_episodes = None
    service.parser_service = Mock(parse=Mock(return_value=ParsedInfo(
        original_filename=source.name, series_name="Test Show"
    )))
    provider.get_season_by_api.return_value = TMDBSeason(
        season_number=1, name="Season 1", episode_count=None, episodes=[]
    )
    result = await execute(request)
    assert result.status == ScrapeStatus.NEED_SEASON_EPISODE
    assert result.series_info.number_of_episodes is None
    assert "集数未知" in result.message
    assert result.parsed_episode is None
    _assert_untouched(service, source, result)
