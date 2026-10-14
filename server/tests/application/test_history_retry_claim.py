"""批量重试领取必须是数据库级原子操作。"""

import asyncio
from datetime import datetime

import pytest

from server.application.history_service import HistoryService
from server.infrastructure.repositories.history_repository import HistoryRepository
from server.models.history import HistoryRecordCreate, TaskStatus


async def make_record(service, status=TaskStatus.PENDING_ACTION):
    return await service.create_record(
        HistoryRecordCreate(
            task_name="批量领取",
            folder_path="/media/Show/01.mp4",
            status=status,
            total_files=1,
            success_count=0,
            failed_count=0,
            duration_seconds=0,
        )
    )


@pytest.mark.asyncio
async def test_only_one_repository_instance_can_claim(temp_db):
    service = HistoryService(temp_db)
    record = await make_record(service)
    repos = [HistoryRepository(temp_db) for _ in range(5)]
    claims = await asyncio.gather(
        *(
            repo.claim_for_retry(record.id, {TaskStatus.PENDING_ACTION}, started_at=datetime.now())
            for repo in repos
        )
    )
    assert claims.count(True) == 1
    updated = await service.get_record(record.id)
    assert updated.status == TaskStatus.RUNNING
    assert updated.started_at is not None
    assert updated.error_message == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [TaskStatus.SUCCESS, TaskStatus.SKIPPED, TaskStatus.CANCELLED, TaskStatus.RUNNING]
)
async def test_claim_never_runs_completed_or_running_records(temp_db, status):
    service = HistoryService(temp_db)
    record = await make_record(service, status)
    # 即使调用方误传成功状态也不能变成破坏性的重刮入口。
    assert not await service.claim_for_retry(record.id, set(TaskStatus))
    assert (await service.get_record(record.id)).status == status


@pytest.mark.asyncio
async def test_claim_enforces_callers_allowed_state(temp_db):
    service = HistoryService(temp_db)
    record = await make_record(service, TaskStatus.FAILED)
    assert not await service.claim_for_retry(record.id, {TaskStatus.PENDING_ACTION})
    assert not await service.claim_for_retry(record.id, set())
    assert not await service.claim_for_retry("missing", {TaskStatus.FAILED})
    assert await service.claim_for_retry(record.id, {TaskStatus.FAILED})
    assert not await service.claim_for_retry(record.id, {TaskStatus.FAILED})


@pytest.mark.asyncio
async def test_claim_survives_realtime_notification_failure(temp_db, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import server.application.history_service as module

    service = HistoryService(temp_db)
    record = await make_record(service)
    notifier = SimpleNamespace(
        notify_history_updated=AsyncMock(side_effect=RuntimeError("offline")),
        notify_history_detail_update=AsyncMock(),
    )
    monkeypatch.setattr(module, "get_notifier", lambda: notifier)
    assert await service.claim_for_retry(record.id, {TaskStatus.PENDING_ACTION})
    assert (await service.get_record(record.id)).status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_cancellation_during_claim_notification_releases_only_own_claim(temp_db, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import server.application.history_service as module

    service = HistoryService(temp_db)
    record = await make_record(service)
    entered = asyncio.Event()

    async def notify(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        module,
        "get_notifier",
        lambda: SimpleNamespace(
            notify_history_updated=notify,
            notify_history_detail_update=AsyncMock(),
        ),
    )
    task = asyncio.create_task(service.claim_for_retry(record.id, {TaskStatus.PENDING_ACTION}))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await service.get_record(record.id)).status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_cancelled_claim_cannot_release_a_newer_execution(temp_db):
    service = HistoryService(temp_db)
    record = await make_record(service)
    old_time, new_time = datetime(2026, 1, 1), datetime(2026, 1, 2)
    assert await service._repo.claim_for_retry(
        record.id, {TaskStatus.PENDING_ACTION}, started_at=new_time
    )
    assert not await service._repo.release_cancelled_retry(record.id, started_at=old_time)
    assert (await service.get_record(record.id)).status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_single_manual_selection_replaces_previous_batch_identity(temp_db, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    import server.bootstrap as bootstrap
    from server.application.history_actions import HistoryScrapeActions
    from server.models.scraper import ScrapeByIdRequest, ScrapeResult, ScrapeStatus

    history = HistoryService(temp_db)
    record = await history.create_record(
        HistoryRecordCreate(
            task_name="换人工版本",
            folder_path="/media/S01E01.mkv",
            status=TaskStatus.PENDING_ACTION,
            total_files=1,
            success_count=0,
            failed_count=0,
            duration_seconds=0,
            conflict_data={
                "batch_selected_id": 2,
                "match_resolved_id": 2,
                "tmdb_id": 2,
                "parsed_season": 1,
                "parsed_episode": 1,
                "series_info": {"id": 2},
                "search_results": [{"id": 2}],
            },
        )
    )
    scraper = SimpleNamespace(
        scrape_by_id=AsyncMock(
            return_value=ScrapeResult(
                file_path=record.folder_path,
                status=ScrapeStatus.API_FAILED,
                message="temporary",
            )
        )
    )
    monkeypatch.setattr(bootstrap, "get_scraper_service", lambda: scraper)
    actions = HistoryScrapeActions(history, None, None)
    with pytest.raises(HTTPException):
        await actions.execute_scrape_and_update(
            record.id,
            ScrapeByIdRequest(
                file_path=record.folder_path,
                tmdb_id=3,
                season=3,
                episode=8,
            ),
        )
    detail = await history.get_record(record.id)
    assert detail.tmdb_id == 3
    assert detail.conflict_data["tmdb_id"] == 3
    assert detail.conflict_data["parsed_season"] == 3
    assert detail.conflict_data["parsed_episode"] == 8
    assert "batch_selected_id" not in detail.conflict_data
    assert "match_resolved_id" not in detail.conflict_data
    assert "series_info" not in detail.conflict_data
    assert "search_results" not in detail.conflict_data
    from server.application.history_batch_actions import HistoryBatchActions

    batch = HistoryBatchActions(history, None, None, actions, scraper=scraper)
    response = await batch.retry([record.id])
    assert not response.results[0].success
    retried = scraper.scrape_by_id.await_args.args[0]
    assert (retried.tmdb_id, retried.season, retried.episode) == (3, 3, 8)
