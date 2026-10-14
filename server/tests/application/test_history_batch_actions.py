"""批量入口按真实源目录分组，逐文件保留集数并安全重试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from server.application.history_batch_actions import HistoryBatchActions
from server.application.history_service import HistoryService
from server.models.ai import AIFolderContext
from server.models.history import HistoryConflictType, HistoryRecordCreate, TaskStatus
from server.models.history_batch import HistoryBatchRequest, HistoryBatchResolveRequest
from server.models.manual_job import ManualJobAdvancedSettings
from server.models.scraper import ScrapeResult, ScrapeStatus


@pytest.fixture
def service(temp_db):
    history = HistoryService(temp_db)
    jobs = SimpleNamespace(get_job=AsyncMock(return_value=None))
    manuals = SimpleNamespace(get_job=AsyncMock(return_value=None))
    actions = SimpleNamespace(
        restore_locators=AsyncMock(return_value={}),
        fill_organize_params=AsyncMock(),
        _finalize=AsyncMock(),
    )
    scraper = SimpleNamespace(
        scrape_file=AsyncMock(), scrape_by_id=AsyncMock(), config_service=None
    )
    return HistoryBatchActions(history, jobs, manuals, actions, scraper=scraper)


async def create(
    service,
    path="/media/Show (2024)/Season 1/S01E01.mkv",
    *,
    status=TaskStatus.PENDING_ACTION,
    conflict=HistoryConflictType.NEED_SELECTION,
    candidates=None,
    extra=None,
    **fields,
):
    context = {
        "advanced_settings": {"r18": False},
        "search_results": candidates
        if candidates is not None
        else [{"id": 1, "name": "Show (2000)"}, {"id": 2, "name": "Show (2024)"}],
    }
    context.update(extra or {})
    record = await service.history.create_record(
        HistoryRecordCreate(
            task_name="测试",
            folder_path=path,
            status=status,
            conflict_type=conflict,
            conflict_data=context,
            total_files=1,
            success_count=0,
            failed_count=0,
            duration_seconds=0,
            **fields,
        )
    )
    return await service.history.get_record(record.id)


@pytest.mark.asyncio
async def test_groups_five_same_show_among_twenty(service):
    records = [
        await create(service, f"/media/Show (2024)/Season 1/S01E{i:02}.mkv") for i in range(1, 6)
    ]
    others = [await create(service, f"/media/Other {i}/S01E01.mkv") for i in range(15)]
    preview = await service.preview([record.id for record in records + others])
    group = next(group for group in preview.groups if len(group.record_ids) == 5)
    assert group.folder_name == "Show (2024)"
    assert set(group.record_ids) == {record.id for record in records}
    assert [candidate.id for candidate in group.candidates] == [1, 2]
    assert len(preview.groups) == 16


@pytest.mark.asyncio
async def test_different_libraries_and_content_modes_do_not_mix(service):
    one = await create(service, "/library-a/Show/S01E01.mkv")
    two = await create(service, "/library-b/Show/S01E02.mkv")
    three = await create(
        service, "/library-a/Show/S01E03.mkv", extra={"advanced_settings": {"r18": True}}
    )
    assert len((await service.preview([one.id, two.id, three.id])).groups) == 3


@pytest.mark.asyncio
async def test_manual_scan_root_finds_outer_show_not_nested_extra_directory(service):
    manual = SimpleNamespace(scan_path="/library")
    service.manual_jobs.get_job.return_value = manual
    one = await create(
        service, "/library/Show (2024)/Encode A/Season 1/S01E01.mkv", manual_job_id=1
    )
    two = await create(
        service, "/library/Show (2024)/Encode B/Season 1/S01E02.mkv", manual_job_id=1
    )
    (group,) = (await service.preview([one.id, two.id])).groups
    assert group.folder_name == "Show (2024)"
    assert len(group.record_ids) == 2


@pytest.mark.asyncio
async def test_scan_show_root_does_not_group_by_season(service):
    service.manual_jobs.get_job.return_value = SimpleNamespace(scan_path="/library/Show")
    one = await create(service, "/library/Show/Season 1/S01E01.mkv", manual_job_id=1)
    two = await create(service, "/library/Show/Season 2/S02E02.mkv", manual_job_id=1)
    (group,) = (await service.preview([one.id, two.id])).groups
    assert group.folder_name == "Show"


@pytest.mark.asyncio
async def test_candidates_are_intersection_and_single_preview_works(service):
    one = await create(service)
    two = await create(service, candidates=[{"id": 2, "name": "Show"}, {"id": 3, "name": "Else"}])
    (group,) = (await service.preview([one.id, two.id])).groups
    assert [candidate.id for candidate in group.candidates] == [2]
    (solo,) = (await service.preview([one.id])).groups
    assert group.group_key == solo.group_key


@pytest.mark.asyncio
async def test_disjoint_candidates_ungrouped_and_bad_context_ignored(service):
    one = await create(service, candidates=[{"id": 4, "name": "A"}])
    two = await create(service, candidates=[{"id": 5, "name": "B"}])
    preview = await service.preview([one.id, two.id])
    assert not preview.groups
    assert set(preview.ungrouped_ids) == {one.id, two.id}


@pytest.mark.asyncio
async def test_cross_directory_resolve_rejected_before_running(service):
    one = await create(service)
    two = await create(service, "/another/Show/S01E02.mkv")
    group = (await service.preview([one.id])).groups[0]
    with pytest.raises(HTTPException):
        await service.resolve(
            HistoryBatchResolveRequest(
                record_ids=[one.id, two.id], group_key=group.group_key, tmdb_id=2
            )
        )
    service._scraper.scrape_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_candidate_rejected(service):
    one = await create(service)
    group = (await service.preview([one.id])).groups[0]
    await service.history.update_record(
        one.id, conflict_data={"search_results": [{"id": 4, "name": "New"}]}
    )
    with pytest.raises(HTTPException):
        await service.resolve(
            HistoryBatchResolveRequest(record_ids=[one.id], group_key=group.group_key, tmdb_id=2)
        )


@pytest.mark.asyncio
async def test_resolve_keeps_each_episode_and_selected_version(service):
    records = [await create(service, f"/media/Show/Season 1/S01E{i:02}.mkv") for i in range(1, 6)]
    service._scraper.scrape_by_id.side_effect = [
        ScrapeResult(
            file_path=r.folder_path,
            status=ScrapeStatus.SUCCESS,
            selected_id=2,
            parsed_season=1,
            parsed_episode=i,
        )
        for i, r in enumerate(records, 1)
    ]
    group = (await service.preview([r.id for r in records])).groups[0]
    result = await service.resolve(
        HistoryBatchResolveRequest(
            record_ids=group.record_ids, group_key=group.group_key, tmdb_id=2
        )
    )
    assert result.success_count == 5
    calls = service._scraper.scrape_by_id.await_args_list
    assert [call.args[0].episode for call in calls] == [1, 2, 3, 4, 5]
    assert all(call.args[0].tmdb_id == 2 and not call.args[0].skip_emby_check for call in calls)
    service._scraper.scrape_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_episode_remains_pending_without_guessing_one(service):
    record = await create(service, "/media/Show/movie.mkv")
    group = (await service.preview([record.id])).groups[0]
    response = await service.resolve(
        HistoryBatchResolveRequest(record_ids=[record.id], group_key=group.group_key, tmdb_id=2)
    )
    current = await service.history.get_record(record.id)
    assert current.status == TaskStatus.PENDING_ACTION
    assert current.conflict_type == HistoryConflictType.NEED_SEASON_EPISODE
    assert response.success_count == 0
    service._scraper.scrape_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_uses_ordinary_scraper_and_preserves_new_candidates(service):
    record = await create(service, conflict=HistoryConflictType.API_FAILED)
    service._scraper.scrape_file.return_value = ScrapeResult(
        file_path=record.folder_path,
        status=ScrapeStatus.NEED_SELECTION,
        search_results=[{"id": 11, "name": "New A"}, {"id": 12, "name": "New B"}],
        parsed_season=1,
        parsed_episode=1,
    )
    response = await service.retry([record.id])
    current = await service.history.get_record(record.id)
    assert current.status == TaskStatus.PENDING_ACTION
    assert current.conflict_type == HistoryConflictType.NEED_SELECTION
    assert current.conflict_data["search_results"][0]["id"] == 11
    assert response.failed_count == 1
    service._scraper.scrape_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_api_failure_keeps_confirmed_version_and_individual_episode(service):
    record = await create(service, conflict=HistoryConflictType.API_FAILED, extra={"tmdb_id": -99})
    service._scraper.scrape_by_id.return_value = ScrapeResult(
        file_path=record.folder_path,
        status=ScrapeStatus.API_FAILED,
        selected_id=-99,
        message="API暂时失败",
    )
    response = await service.retry([record.id])
    request = service._scraper.scrape_by_id.await_args.args[0]
    assert (request.tmdb_id, request.episode) == (-99, 1)
    assert response.results[0].status == TaskStatus.PENDING_ACTION
    assert not response.results[0].success


@pytest.mark.asyncio
async def test_retry_success_and_running_are_not_executed(service):
    records = [
        await create(service, status=status)
        for status in [TaskStatus.SUCCESS, TaskStatus.RUNNING, TaskStatus.SKIPPED]
    ]
    result = await service.retry([record.id for record in records])
    assert result.failed_count == 3
    service._scraper.scrape_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_source_not_product_no_cleanup_and_no_force(service):
    record = await create(
        service,
        "/media/Show/S01E02.mkv => /output/Show/E02.mkv",
        conflict=HistoryConflictType.FILE_CONFLICT,
    )
    service._scraper.scrape_file.return_value = ScrapeResult(
        file_path="/media/Show/S01E02.mkv", status=ScrapeStatus.FILE_CONFLICT, message="已存在"
    )
    response = await service.retry([record.id])
    request = service._scraper.scrape_file.await_args.args[0]
    assert request.file_path == "/media/Show/S01E02.mkv"
    assert response.results[0].status == TaskStatus.PENDING_ACTION
    assert not hasattr(service.actions, "prepare_input")


@pytest.mark.asyncio
async def test_concurrent_retry_claim_only_executes_once(service):
    record = await create(service)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow(*args, **kwargs):
        entered.set()
        await release.wait()
        return ScrapeResult(file_path=record.folder_path, status=ScrapeStatus.NO_MATCH)

    service._scraper.scrape_file.side_effect = slow
    first = asyncio.create_task(service.retry([record.id]))
    await entered.wait()
    second = await service.retry([record.id])
    release.set()
    await first
    assert second.failed_count == 1
    service._scraper.scrape_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_exception_isolated_and_running_is_released(service):
    one = await create(service)
    two = await create(service)
    service._scraper.scrape_file.side_effect = [
        RuntimeError("secret"),
        ScrapeResult(file_path=two.folder_path, status=ScrapeStatus.NO_MATCH),
    ]
    result = await service.retry([one.id, two.id])
    assert result.failed_count == 2
    assert (await service.history.get_record(one.id)).status == TaskStatus.FAILED
    assert (await service.history.get_record(two.id)).status == TaskStatus.PENDING_ACTION
    assert "secret" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_cancellation_releases_running(service):
    record = await create(service)
    service._scraper.scrape_file.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.retry([record.id])
    assert (await service.history.get_record(record.id)).status == TaskStatus.FAILED


def test_request_limit_and_deduplication():
    assert HistoryBatchRequest(record_ids=["a", "a", "b"]).record_ids == ["a", "b"]
    for values in [[], ["a"] * 101, [" "]]:
        with pytest.raises(ValidationError):
            HistoryBatchRequest(record_ids=values)


@pytest.mark.asyncio
async def test_pure_directory_hint_does_not_merge_libraries(service):
    context = AIFolderContext(outer_folder_name="Show", folder_names=["Show"])
    records = [
        await create(service, path, extra={"ai_folder_context": context.model_dump()})
        for path in ["/one/Show/Enc/Season 1/E01.mkv", "/two/Show/Enc/Season 1/E02.mkv"]
    ]
    groups = (await service.preview([record.id for record in records])).groups
    assert len(groups) == 2
    assert groups[0].folder_name == groups[1].folder_name == "Enc"
    assert groups[0].group_key != groups[1].group_key


@pytest.mark.asyncio
async def test_windows_same_outer_directory_groups_seasons(service):
    one = await create(service, r"D:\library\Show\Season 1\S01E01.mkv")
    two = await create(service, r"D:\library\Show\Season 2\S02E02.mkv")
    (group,) = (await service.preview([one.id, two.id])).groups
    assert group.folder_name == "Show"


@pytest.mark.asyncio
async def test_invalid_candidates_and_nonpending_go_ungrouped(service):
    records = [
        await create(service, candidates=None, extra={"search_results": value})
        for value in [None, {}, [{"name": "missing ID"}], []]
    ]
    records.append(await create(service, status=TaskStatus.RUNNING))
    preview = await service.preview([record.id for record in records] + ["missing-id"])
    assert not preview.groups
    assert len(preview.ungrouped_ids) == 6


@pytest.mark.asyncio
async def test_timeout_keeps_resolved_id_and_retry_uses_same_version(service):
    record = await create(service)
    service._scraper.config_service = SimpleNamespace(
        get_system_config=AsyncMock(return_value=SimpleNamespace(task_timeout=0.01))
    )

    async def slow(request, *, on_log_update, on_match_resolved):
        await on_match_resolved(42, 1, 1)
        await asyncio.Event().wait()

    service._scraper.scrape_file.side_effect = slow
    response = await service.retry([record.id])
    current = await service.history.get_record(record.id)
    assert response.results[0].status == TaskStatus.TIMEOUT
    assert current.conflict_data["match_resolved_id"] == 42
    service._scraper.scrape_by_id.return_value = ScrapeResult(
        file_path=record.folder_path, status=ScrapeStatus.API_FAILED
    )
    await service.retry([record.id])
    assert service._scraper.scrape_by_id.await_args.args[0].tmdb_id == 42


@pytest.mark.asyncio
async def test_preserves_job_locators_settings_and_directory_context(service):
    from server.models.storage import StorageLocator, StorageProvider

    record = await create(service)
    locator = StorageLocator(
        provider=StorageProvider.P115, path=record.folder_path, file_id="123", is_dir=False
    )
    context = AIFolderContext(outer_folder_name="Show", folder_names=["Show"])
    settings = ManualJobAdvancedSettings(r18=False, ai_assist=False)
    service.actions.restore_locators.return_value = {
        "file_locator": locator,
        "allow_local_output": True,
        "advanced_settings": settings,
        "ai_folder_context": context,
    }
    service._scraper.scrape_file.return_value = ScrapeResult(
        file_path=record.folder_path, status=ScrapeStatus.NO_MATCH
    )
    await service.retry([record.id])
    request = service._scraper.scrape_file.await_args.args[0]
    assert request.file_locator == locator
    assert request.allow_local_output
    assert request.advanced_settings == settings
    assert request.ai_folder_context == context


@pytest.mark.asyncio
async def test_missing_related_task_falls_back_to_source_directory(service):
    records = [
        await create(
            service,
            f"/media/Show/Season 1/S01E{i:02}.mkv",
            scrape_job_id=f"gone-{i}",
            manual_job_id=1,
        )
        for i in [1, 2]
    ]
    service.jobs.get_job.side_effect = RuntimeError("deleted job")
    service.manual_jobs.get_job.side_effect = RuntimeError("deleted manual")
    (group,) = (await service.preview([record.id for record in records])).groups
    assert group.folder_name == "Show"
    assert len(group.record_ids) == 2


@pytest.mark.asyncio
async def test_preflight_failure_does_not_abort_other_items(service):
    one = await create(service)
    two = await create(service)
    actual_get = service.history.get_record

    async def selective_get(record_id):
        if record_id == one.id:
            raise RuntimeError("unreadable record")
        return await actual_get(record_id)

    service.history.get_record = selective_get
    service._scraper.scrape_file.return_value = ScrapeResult(
        file_path=two.folder_path, status=ScrapeStatus.NO_MATCH
    )
    response = await service.retry([one.id, two.id])
    assert response.failed_count == 2
    assert response.results[0].status is None
    assert response.results[1].status == TaskStatus.PENDING_ACTION
    service._scraper.scrape_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_single_file_scan_can_preview(service):
    record = await create(service, "/library/Show/S01E01.mkv", manual_job_id=1)
    service.manual_jobs.get_job.return_value = SimpleNamespace(scan_path=record.folder_path)
    (group,) = (await service.preview([record.id])).groups
    assert group.folder_name == "Show"


@pytest.mark.asyncio
async def test_manual_scan_locator_takes_precedence_over_placeholder(service):
    from server.models.storage import StorageLocator, StorageProvider

    locator = StorageLocator(provider=StorageProvider.P115, path="/cloud/library", is_dir=True)
    service.manual_jobs.get_job.return_value = SimpleNamespace(
        scan_path="/placeholder", scan_locator=locator
    )
    records = [
        await create(
            service, f"/cloud/library/Show/Enc {i}/Season 1/S01E{i:02}.mkv", manual_job_id=1
        )
        for i in [1, 2]
    ]
    (group,) = (await service.preview([record.id for record in records])).groups
    assert group.folder_name == "Show"
    assert len(group.record_ids) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conflict",
    [
        HistoryConflictType.FILE_CONFLICT,
        HistoryConflictType.EMBY_CONFLICT,
        HistoryConflictType.API_FAILED,
    ],
)
async def test_old_confirmed_context_keeps_individual_season_episode(service, conflict):
    record = await create(
        service,
        "/media/Show/S01E01.mkv",
        conflict=conflict,
        extra={"tmdb_id": 123, "season": 3, "episode": 8},
    )
    service._scraper.scrape_by_id.return_value = ScrapeResult(
        file_path=record.folder_path, status=ScrapeStatus.API_FAILED
    )
    await service.retry([record.id])
    request = service._scraper.scrape_by_id.await_args.args[0]
    assert (request.tmdb_id, request.season, request.episode) == (123, 3, 8)
    assert not request.skip_emby_check


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [TaskStatus.TIMEOUT, TaskStatus.FAILED])
async def test_old_timeout_confirmed_record_columns_preserve_match(service, status):
    record = await create(service, "/media/Show/unknown.mkv", status=status, conflict=None)
    await service.history.update_record(record.id, tmdb_id=123, season_number=3, episode_number=8)
    service._scraper.scrape_by_id.return_value = ScrapeResult(
        file_path=record.folder_path, status=ScrapeStatus.API_FAILED
    )
    await service.retry([record.id])
    request = service._scraper.scrape_by_id.await_args.args[0]
    assert (request.tmdb_id, request.season, request.episode) == (123, 3, 8)
    service._scraper.scrape_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_unknown_root_builder_never_merges_different_shows(service):
    from server.domain.metadata.folder_context import build_ai_folder_context

    records = []
    for path in ["/media/ShowA/E01.mkv", "/media/ShowB/E01.mkv"]:
        context = build_ai_folder_context(path)
        assert context.outer_folder_name == "media"
        records.append(
            await create(service, path, extra={"ai_folder_context": context.model_dump()})
        )
    groups = (await service.preview([record.id for record in records])).groups
    assert {group.folder_name for group in groups} == {"ShowA", "ShowB"}
    assert len(groups) == 2


@pytest.mark.asyncio
async def test_verified_named_scan_root_context_groups_nested_same_show(service):
    from server.domain.metadata.folder_context import build_ai_folder_context

    records = []
    for i in [1, 2]:
        path = f"/media/Show/Encode {i}/Season 1/E0{i}.mkv"
        context = build_ai_folder_context(path, "/media")
        records.append(
            await create(service, path, extra={"ai_folder_context": context.model_dump()})
        )
    (group,) = (await service.preview([record.id for record in records])).groups
    assert group.folder_name == "Show"
    assert len(group.record_ids) == 2
