"""目录名称上下文在历史快照和恢复中保持，且不携带完整路径。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.application.history_actions import HistoryScrapeActions
from server.application.history_service import HistoryService
from server.models.ai import AIFolderContext
from server.models.history import HistoryRecordCreate, TaskStatus


@pytest.fixture
def context():
    return AIFolderContext(
        scan_root_name="电视剧",
        outer_folder_name="作品 (2024)",
        parent_folder_name="Season 1",
        folder_names=["电视剧", "作品 (2024)", "Season 1"],
    )


@pytest.mark.asyncio
async def test_history_snapshot_keeps_names_for_deleted_job(temp_db, context):
    service = HistoryService(temp_db)
    record = await service.create_record(
        HistoryRecordCreate(
            task_name="目录识别",
            folder_path="/media/电视剧/作品 (2024)/Season 1/01.mp4",
            status=TaskStatus.PENDING_ACTION,
            total_files=1,
            success_count=0,
            failed_count=0,
            duration_seconds=0,
            scrape_job_id="old-job",
            conflict_data={
                "advanced_settings": {"r18": False},
                "ai_folder_context": context.model_dump(),
            },
        )
    )
    detail = await service.get_record(record.id)
    records, _ = await service.list_records()
    assert detail.ai_folder_context == context
    assert records[0].ai_folder_context == context
    jobs = SimpleNamespace(get_job=AsyncMock(return_value=None))
    actions = HistoryScrapeActions(service, jobs, None)
    restored = await actions.restore_locators(detail)
    assert restored["ai_folder_context"] == context
    assert "/media" not in restored["ai_folder_context"].model_dump_json()


@pytest.mark.asyncio
async def test_history_prefers_task_names_over_record_fallback(context):
    task_context = AIFolderContext(folder_names=["另一个作品"])
    jobs = SimpleNamespace(
        get_job=AsyncMock(
            return_value=SimpleNamespace(
                file_locator=None,
                output_locator=None,
                metadata_locator=None,
                allow_local_output=False,
                advanced_settings=None,
                ai_folder_context=task_context,
            )
        )
    )
    actions = HistoryScrapeActions(None, jobs, None)
    record = SimpleNamespace(scrape_job_id="job", advanced_settings=None, ai_folder_context=context)
    restored = await actions.restore_locators(record)
    assert restored["ai_folder_context"] == task_context


@pytest.mark.asyncio
async def test_old_history_does_not_invent_scan_root(temp_db):
    service = HistoryService(temp_db)
    record = await service.create_record(
        HistoryRecordCreate(
            task_name="旧任务",
            folder_path="/private/media/Season 1/01.mp4",
            status=TaskStatus.PENDING_ACTION,
            total_files=1,
            success_count=0,
            failed_count=0,
            duration_seconds=0,
        )
    )
    detail = await service.get_record(record.id)
    assert detail.ai_folder_context is None
    restored = await HistoryScrapeActions(service, None, None).restore_locators(detail)
    assert restored == {}


@pytest.mark.asyncio
async def test_history_invalid_context_is_not_forwarded(temp_db):
    service = HistoryService(temp_db)
    record = await service.create_record(
        HistoryRecordCreate(
            task_name="无效上下文",
            folder_path="/media/a.mp4",
            status=TaskStatus.PENDING_ACTION,
            total_files=1,
            success_count=0,
            failed_count=0,
            duration_seconds=0,
            conflict_data={"ai_folder_context": {"folder_names": ["/private/user"]}},
        )
    )
    detail = await service.get_record(record.id)
    assert detail.ai_folder_context is None


@pytest.mark.asyncio
async def test_invalid_job_context_does_not_block_ordinary_job_load(temp_db, monkeypatch):
    import aiosqlite

    import server.application.scrape_job_service as scrape_module
    from server.application.scrape_job_service import ScrapeJobService
    from server.models.scrape_job import ScrapeJobCreate

    monkeypatch.setattr(scrape_module, "_ensure_worker", lambda: None)
    service = ScrapeJobService(temp_db)
    created = await service.create_job(
        ScrapeJobCreate(file_path="/media/Show/01.mp4", output_dir="/out")
    )
    async with aiosqlite.connect(temp_db) as db:
        await db.execute(
            "UPDATE scrape_jobs SET ai_folder_context=? WHERE id=?",
            ('{"folder_names":["/private/not-a-name"]}', created.id),
        )
        await db.commit()
    job = await service.get_job(created.id)
    assert job is not None
    assert job.file_path == "/media/Show/01.mp4"
    assert job.ai_folder_context is None
