"""表番模式快照、离线身份与 Emby 边界回归。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.application.history_actions import HistoryScrapeActions, rebuild_metadata
from server.application.history_service import HistoryService, _metadata_context
from server.application.scraping.media_pipeline import ScraperMediaPipeline
from server.models.history import HistoryRecordCreate, TaskStatus
from server.models.manual_job import ManualJobAdvancedSettings


def test_history_context_retains_legacy_adult_mode():
    assert _metadata_context({"conflict_data": None, "tmdb_id": 42})["advanced_settings"].r18


def test_history_context_reads_anilist_identity_and_mode():
    context = _metadata_context(
        {
            "conflict_data": '{"advanced_settings":{"r18":false},"anilist_id":123}',
            "tmdb_id": -123,
        }
    )
    assert context["metadata_source"] == "anilist"
    assert context["anilist_id"] == 123
    assert not context["advanced_settings"].r18


@pytest.mark.asyncio
async def test_history_snapshot_roundtrip(temp_db):
    service = HistoryService(temp_db)
    result = await service.create_record(
        HistoryRecordCreate(
            task_name="表番",
            folder_path="/media/anime.mkv",
            status=TaskStatus.RUNNING,
            total_files=1,
            success_count=0,
            failed_count=0,
            duration_seconds=0,
            conflict_data={"advanced_settings": {"r18": False}, "anilist_id": 123},
        )
    )
    await service.update_record(result.id, tmdb_id=-123)
    detail = await service.get_record(result.id)
    records, _ = await service.list_records()
    for record in (detail, records[0]):
        assert record.metadata_source == "anilist"
        assert record.anilist_id == 123
        assert not record.advanced_settings.r18


def test_rebuild_anilist_does_not_invent_tmdb_identity():
    record = SimpleNamespace(
        episode_title="Episode 2",
        episode_overview=None,
        episode_air_date=None,
        episode_still_url=None,
        title="动画",
        original_title="Anime",
        plot="简介",
        release_date=None,
        rating=8.0,
        poster_url="https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/a.jpg",
        tags=["Action"],
        anilist_id=123,
    )
    series, season = rebuild_metadata(record, tmdb_id=-123, season_num=1, episode_num=2)
    assert series.metadata_source == "anilist"
    assert series.anilist_id == 123
    assert series.poster_path == record.poster_url
    assert season.episodes[0].episode_number == 2


@pytest.mark.asyncio
async def test_restore_locators_preserves_mode():
    settings = ManualJobAdvancedSettings(r18=True)
    jobs = SimpleNamespace(
        get_job=AsyncMock(
            return_value=SimpleNamespace(
                file_locator=None,
                output_locator=None,
                metadata_locator=None,
                allow_local_output=False,
                advanced_settings=settings,
            )
        )
    )
    actions = HistoryScrapeActions(None, jobs, None)
    result = await actions.restore_locators(
        SimpleNamespace(scrape_job_id="job", advanced_settings=settings)
    )
    assert result["advanced_settings"].r18


@pytest.mark.asyncio
async def test_anilist_internal_id_not_sent_to_emby():
    emby = SimpleNamespace(
        get_config=AsyncMock(return_value=SimpleNamespace(enabled=True, check_before_scrape=True)),
        check_conflict=AsyncMock(),
    )
    service = ScraperMediaPipeline(None, None, emby)
    await service.check_emby_conflict("Anime", -123, 1, 2)
    request = emby.check_conflict.await_args.args[0]
    assert request.tmdb_id is None
    assert request.series_name == "Anime"


@pytest.mark.asyncio
async def test_rescrape_source_switch_clears_old_dates_even_if_registration_fails(temp_db):
    from server.models.scraper import ScrapeResult, ScrapeStatus
    from server.models.tmdb import TMDBEpisode, TMDBSeries

    history = HistoryService(temp_db)
    record = await history.create_record(
        HistoryRecordCreate(
            task_name="换源",
            folder_path="/media/a.mkv",
            status=TaskStatus.PENDING_ACTION,
            total_files=1,
            success_count=0,
            failed_count=0,
            duration_seconds=0,
            conflict_data={
                "advanced_settings": {"r18": False},
                "tmdb_id": 100,
                "series_info": {"anilist_id": 999},
            },
        )
    )
    await history.update_record(
        record.id,
        tmdb_id=100,
        plot="旧简介",
        poster_url="/old.jpg",
        episode_air_date="2020-01-01",
        episode_overview="旧单集剧情",
    )
    scraped = SimpleNamespace(register_output=AsyncMock(side_effect=RuntimeError("登记失败")))
    actions = HistoryScrapeActions(history, None, scraped)
    result = ScrapeResult(
        file_path="/media/a.mkv",
        status=ScrapeStatus.SUCCESS,
        selected_id=-20,
        parsed_season=1,
        parsed_episode=1,
        dest_path="/target/a.mkv",
        series_info=TMDBSeries(id=-20, name="新动画", metadata_source="anilist", anilist_id=20),
        episode_info=TMDBEpisode(episode_number=1, name="Episode 1"),
    )
    response = await actions._finalize(record.id, result, manual_job_id=None, duration_seconds=1)
    assert response["success"]
    detail = await history.get_record(record.id)
    assert detail.tmdb_id == -20
    assert detail.conflict_data["tmdb_id"] == -20
    assert detail.anilist_id == 20
    assert "series_info" not in detail.conflict_data
    assert detail.plot is None
    assert detail.poster_url is None
    assert detail.episode_air_date is None
    assert detail.episode_overview is None
    series, season = rebuild_metadata(detail, tmdb_id=detail.tmdb_id, season_num=1, episode_num=1)
    assert series.metadata_source == "anilist"
    assert season.episodes[0].air_date is None


@pytest.mark.asyncio
async def test_explicit_metadata_replacement_emits_null_to_live_client(temp_db):
    from unittest.mock import patch

    service = HistoryService(temp_db)
    record = await service.create_record(
        HistoryRecordCreate(
            task_name="清字段",
            folder_path="/media/a.mkv",
            status=TaskStatus.RUNNING,
            total_files=1,
            success_count=0,
            failed_count=0,
            duration_seconds=0,
        )
    )
    notifier = AsyncMock()
    with patch("server.application.history_service.get_notifier", return_value=notifier):
        await service.update_record(record.id, title="动画", replace_metadata=True)
    payload = notifier.notify_history_detail_update.await_args.args[1]
    assert "episode_air_date" in payload
    assert payload["episode_air_date"] is None
    assert payload["tags"] == []


@pytest.mark.asyncio
async def test_new_manual_and_scrape_jobs_snapshot_default_anime_mode(temp_db, monkeypatch):
    import json

    import aiosqlite

    import server.application.manual_job_service as manual_module
    import server.application.scrape_job_service as scrape_module
    from server.application.manual_job_service import ManualJobService
    from server.application.scrape_job_service import ScrapeJobService
    from server.models.manual_job import ManualJobCreate
    from server.models.scrape_job import ScrapeJobCreate

    monkeypatch.setattr(manual_module, "_ensure_worker", lambda: None)
    monkeypatch.setattr(scrape_module, "_ensure_worker", lambda: None)
    manual_service = ManualJobService(temp_db)
    scrape_service = ScrapeJobService(temp_db)
    manual = await manual_service.create_job(ManualJobCreate(scan_path="/a", target_folder="/b"))
    scrape = await scrape_service.create_job(ScrapeJobCreate(file_path="/a.mkv", output_dir="/b"))
    assert not manual.advanced_settings.r18
    assert not scrape.advanced_settings.r18
    for service, job, table in (
        (manual_service, manual, "manual_jobs"),
        (scrape_service, scrape, "scrape_jobs"),
    ):
        loaded = await service.get_job(job.id)
        assert not loaded.advanced_settings.r18
        # 模拟原版没有 r18 字段的任务，只有临时测试库发生修改。
        async with aiosqlite.connect(temp_db) as db:
            await db.execute(
                f"UPDATE {table} SET advanced_settings = ? WHERE id = ?",
                (json.dumps({"nfo_enabled": True}), job.id),
            )
            await db.commit()
        old = await service.get_job(job.id)
        assert old.advanced_settings.r18


@pytest.mark.asyncio
async def test_anilist_candidates_do_not_trigger_redundant_details():
    from server.application.scraping.metadata_resolver import ScraperMetadataResolver
    from server.models.tmdb import TMDBSearchResult

    provider = SimpleNamespace(get_series_by_api=AsyncMock())
    resolver = ScraperMetadataResolver(provider, None)
    candidate = TMDBSearchResult(
        id=-20, name="Anime", metadata_source="anilist", number_of_episodes=12
    )
    results = await resolver.enrich_search_results([candidate], provider)
    assert results[0].number_of_episodes == 12
    provider.get_series_by_api.assert_not_awaited()
