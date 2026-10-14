"""目录辅助信息的隐私边界、队列投递与持久化回归。"""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiosqlite
import pytest
from pydantic import ValidationError

from server.application import manual_job_service as manual_module
from server.application import scrape_job_service as scrape_module
from server.application.scrape_job_service import ScrapeJobService
from server.application.watcher_service import WatcherService
from server.domain.metadata.folder_context import build_ai_folder_context
from server.infrastructure.repositories.scrape_job_repository import ScrapeJobRepository
from server.models.ai import AIFolderContext
from server.models.manual_job import LinkMode
from server.models.organize import OrganizeMode
from server.models.scrape_job import ScrapeJobCreate
from server.models.scraper import BatchScrapeRequest, ScrapeByIdRequest, ScrapeRequest
from server.models.storage import StorageLocator, StorageProvider
from server.models.watcher import DetectedFile, WatchedFolder


@pytest.mark.parametrize(
    ("file_path", "scan_root", "expected", "outer"),
    [
        (
            "/media/电视剧/作品(2024)/Season 1/01.mp4",
            "/media/电视剧",
            ["电视剧", "作品(2024)", "Season 1"],
            "作品(2024)",
        ),
        (
            "/media/作品(2024)/Season 1/01.mp4",
            "/media/作品(2024)",
            ["作品(2024)", "Season 1"],
            "Season 1",
        ),
        ("/media/作品/01.mp4", "/media/作品", ["作品"], "作品"),
        (
            r"D:\media\电视剧\作品\Season 1\01.mp4",
            r"D:\media\电视剧",
            ["电视剧", "作品", "Season 1"],
            "作品",
        ),
        (
            r"\\private-server\share\media\电视剧\作品\Season 1\01.mp4",
            r"\\private-server\share\media\电视剧",
            ["电视剧", "作品", "Season 1"],
            "作品",
        ),
        (
            "///115网盘//电视剧/作品/Season 1/01.mp4",
            "/115网盘/电视剧",
            ["电视剧", "作品", "Season 1"],
            "作品",
        ),
        ("/media/作品/Season 1/01.mp4", "/media/其他", ["作品", "Season 1"], "作品"),
        ("/private/secret/作品/Season 1/01.mp4", None, ["作品", "Season 1"], "作品"),
        ("/作品/01.mp4", None, ["作品"], "作品"),
        ("01.mp4", None, [], None),
        ("/01.mp4", "/", [], None),
        (
            "/media/电视剧/作品/a/b/c/Season 1/01.mp4",
            "/media/电视剧",
            ["电视剧", "作品", "c", "Season 1"],
            "作品",
        ),
    ],
)
def test_lexical_context_excludes_path_ancestors(file_path, scan_root, expected, outer):
    context = build_ai_folder_context(file_path, scan_root)
    assert context.folder_names == expected
    assert context.outer_folder_name == outer
    assert context.parent_folder_name == (expected[-1] if expected else None)
    assert len(context.folder_names) <= 4
    payload = context.model_dump_json()
    assert "private-server" not in payload
    assert "secret" not in payload
    assert "media" not in payload
    assert ":" not in "".join(context.folder_names)
    assert not any("/" in name or "\\" in name for name in context.folder_names)


def test_clean_control_characters_and_long_names_without_io(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "stat", Mock(side_effect=AssertionError("禁止访问文件系统")))
    context = build_ai_folder_context("/root/作\n品\x00/" + "长" * 200 + "/01.mp4", "/root")
    assert context.folder_names == ["root", "作品", "长" * 160]
    assert context.parent_folder_name == "长" * 160
    assert build_ai_folder_context("/root/../private/01.mp4", "/root").folder_names == []
    assert build_ai_folder_context("https://host/private/01.mp4").folder_names == []


@pytest.mark.parametrize(
    "name", ["/private/作品", r"C:\private\作品", "D:作品", "https://host", "www.host"]
)
def test_context_rejects_path_or_url_as_name(name):
    with pytest.raises(ValidationError):
        AIFolderContext(folder_names=[name])
    with pytest.raises(ValidationError):
        AIFolderContext(outer_folder_name=name)


def test_context_filters_empty_names_and_rejects_excess_names():
    assert AIFolderContext(folder_names=["", ".", "..", "\n"]).folder_names == []
    assert AIFolderContext(outer_folder_name=".").outer_folder_name is None
    with pytest.raises(ValidationError):
        AIFolderContext(folder_names=["a", "b", "c", "d", "e"])


@pytest.mark.parametrize(
    "model", [ScrapeRequest, BatchScrapeRequest, ScrapeByIdRequest, ScrapeJobCreate]
)
def test_request_models_keep_context_separate_from_advanced_settings(model):
    kwargs = {"file_path": "/root/作品/01.mp4", "output_dir": "/output"}
    if model is BatchScrapeRequest:
        kwargs["file_paths"] = [kwargs.pop("file_path")]
    if model is ScrapeByIdRequest:
        kwargs.update(tmdb_id=1, season=1, episode=1)
    context = build_ai_folder_context("/root/作品/01.mp4", "/root")
    request = model(**kwargs, ai_folder_context=context)
    assert request.ai_folder_context == context
    assert request.advanced_settings is None


@pytest.mark.asyncio
async def test_old_schema_migration_is_idempotent_and_preserves_old_none(tmp_path):
    db_path = tmp_path / "old.db"
    async with aiosqlite.connect(db_path) as db:
        # 项目创建的旧库已经开启 WAL，避免并发测试混入连接基类的 WAL 初始化竞态。
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            """CREATE TABLE scrape_jobs (
                id TEXT PRIMARY KEY, file_path TEXT NOT NULL, output_dir TEXT NOT NULL,
                metadata_dir TEXT, source TEXT NOT NULL, source_id INTEGER,
                status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT,
                finished_at TEXT, error_message TEXT, history_record_id TEXT
            )"""
        )
        await db.execute(
            """INSERT INTO scrape_jobs (id, file_path, output_dir, source, status, created_at)
            VALUES ('old', '/root/01.mp4', '/output', 'manual', 'pending', '2026-01-01')"""
        )
        await db.commit()
    repository = ScrapeJobRepository(db_path)
    await asyncio.gather(*(ScrapeJobRepository(db_path).ensure_schema() for _ in range(4)))
    await repository.ensure_schema()
    await repository.ensure_schema()
    service = ScrapeJobService(db_path=db_path)
    old = await service.get_job("old")
    assert old.ai_folder_context is None
    async with aiosqlite.connect(db_path) as db:
        columns = await (await db.execute("PRAGMA table_info(scrape_jobs)")).fetchall()
    assert [row[1] for row in columns].count("ai_folder_context") == 1


@pytest.mark.asyncio
async def test_create_job_persists_names_only_and_restores_context(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_module, "_ensure_worker", lambda: None)
    monkeypatch.setattr(
        scrape_module, "get_notifier", lambda: SimpleNamespace(notify_job_created=AsyncMock())
    )
    service = ScrapeJobService(db_path=tmp_path / "new.db")
    path = "/private/library/作品/Season 1/01.mp4"
    context = build_ai_folder_context(path, "/private/library")
    created = await service.create_job(
        ScrapeJobCreate(file_path=path, output_dir="/output", ai_folder_context=context)
    )
    assert created.ai_folder_context == context
    loaded = await service.get_job(created.id)
    assert loaded.ai_folder_context == context
    row = await service._repo.get_job_raw(created.id)
    assert "private" not in row["ai_folder_context"]
    assert "/" not in row["ai_folder_context"]
    assert "ai_folder_context" not in row["advanced_settings"]


@pytest.mark.asyncio
@pytest.mark.parametrize("single_file", [False, True])
async def test_manual_dispatch_uses_scan_root_or_single_file_nearest_folders(
    tmp_path, monkeypatch, single_file
):
    from server.domain.media.file_service import FileService

    root = tmp_path / "电视剧"
    source = root / "作品" / "Season 1" / "01.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    scan_path = str(source if single_file else root)
    job = SimpleNamespace(
        scan_path=scan_path,
        scan_locator=None,
        target_folder="/output",
        target_locator=None,
        metadata_dir=None,
        metadata_locator=None,
        allow_local_output=False,
        link_mode=LinkMode.COPY,
        advanced_settings=None,
        delete_empty_parent=False,
    )
    service = SimpleNamespace(get_job=AsyncMock(return_value=job), update_job_status=AsyncMock())
    create = AsyncMock(return_value=object())
    monkeypatch.setattr(ScrapeJobService, "create_job", create)
    monkeypatch.setattr(
        FileService, "scan_folder", lambda *args: [SimpleNamespace(path=str(source))]
    )
    await manual_module._execute_job(service, 7)
    request = create.await_args.args[0]
    assert request.file_path == str(source)
    assert request.ai_folder_context.scan_root_name == (None if single_file else "电视剧")
    assert request.ai_folder_context.folder_names == (
        ["作品", "Season 1"] if single_file else ["电视剧", "作品", "Season 1"]
    )


@pytest.mark.asyncio
async def test_manual_cloud_dispatch_prefers_locator_root_and_preserves_ids(monkeypatch):
    from server.domain.media.file_service import FileService

    locator = StorageLocator(
        provider=StorageProvider.P115, path="/115网盘/电视剧", file_id="private-id", is_dir=True
    )
    path = "/115网盘/电视剧/作品/Season 1/01.mp4"
    job = SimpleNamespace(
        scan_path="/placeholder",
        scan_locator=locator,
        target_folder="/output",
        target_locator=None,
        metadata_dir=None,
        metadata_locator=None,
        allow_local_output=False,
        link_mode=LinkMode.COPY,
        advanced_settings=None,
        delete_empty_parent=False,
    )
    scanned = SimpleNamespace(path=path, file_id="video-id", parent_id="season-id")
    service = SimpleNamespace(get_job=AsyncMock(return_value=job), update_job_status=AsyncMock())
    create = AsyncMock(return_value=object())
    monkeypatch.setattr(ScrapeJobService, "create_job", create)
    monkeypatch.setattr(FileService, "scan_folder_async", AsyncMock(return_value=[scanned]))
    await manual_module._execute_job(service, 8)
    request = create.await_args.args[0]
    assert request.ai_folder_context.folder_names == ["电视剧", "作品", "Season 1"]
    assert "id" not in request.ai_folder_context.model_dump_json()
    assert request.file_locator.file_id == "video-id"
    assert request.file_locator.path == path


@pytest.mark.asyncio
async def test_watcher_dispatch_uses_actual_monitored_folder_root(monkeypatch, tmp_path):
    from server.domain.system.config_service import ConfigService

    monkeypatch.setattr(
        ConfigService,
        "get_organize_config",
        AsyncMock(
            return_value=SimpleNamespace(
                organize_dir="/output", metadata_dir=None, organize_mode=OrganizeMode.COPY
            )
        ),
    )
    create = AsyncMock(return_value=object())
    monkeypatch.setattr(ScrapeJobService, "create_job", create)
    folder = WatchedFolder(id="watch", path="/media/电视剧")
    file = DetectedFile(
        path="/media/电视剧/作品/Season 1/01.mp4", detected_at=datetime.now(), file_size=100
    )
    watcher = WatcherService(db_path=tmp_path / "watch.db")
    await watcher._create_jobs_for_files([file], folder)
    request = create.await_args.args[0]
    assert request.ai_folder_context.folder_names == ["电视剧", "作品", "Season 1"]
    assert request.file_path == file.path


@pytest.mark.asyncio
async def test_migration_database_errors_are_not_silenced(monkeypatch, tmp_path):
    from contextlib import asynccontextmanager

    repository = ScrapeJobRepository(tmp_path / "broken.db")

    @asynccontextmanager
    async def broken_connection():
        yield SimpleNamespace(execute=AsyncMock(side_effect=aiosqlite.OperationalError("disk I/O")))

    monkeypatch.setattr(repository, "_connect", broken_connection)
    with pytest.raises(aiosqlite.OperationalError, match="disk I/O"):
        await repository.ensure_schema()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_name",
    [
        "SUCCESS",
        "NEED_SELECTION",
        "NEED_SEASON_EPISODE",
        "FILE_CONFLICT",
        "NO_MATCH",
        "API_FAILED",
        "SEARCH_FAILED",
        "EMBY_CONFLICT",
    ],
)
async def test_worker_passes_context_and_preserves_all_history_snapshots(
    tmp_path, monkeypatch, status_name
):
    from server.models.scrape_job import ScrapeJob, ScrapeJobSource
    from server.models.scraper import ScrapeResult, ScrapeStatus

    source = tmp_path / "作品" / "Season 1" / "01.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    context = build_ai_folder_context(str(source))
    job = ScrapeJob(
        id="contextjob",
        file_path=str(source),
        output_dir=str(tmp_path / "output"),
        source=ScrapeJobSource.MANUAL,
        created_at=datetime.now(),
        ai_folder_context=context,
    )
    service = SimpleNamespace(get_job=AsyncMock(return_value=job), update_job=AsyncMock())
    history = SimpleNamespace(
        create_record=AsyncMock(return_value=SimpleNamespace(id="record")),
        update_record=AsyncMock(),
        update_record_on_success=AsyncMock(),
        update_scrape_logs=AsyncMock(),
        clear_log_cache=Mock(),
    )
    status = getattr(ScrapeStatus, status_name)
    scraper = SimpleNamespace(
        scrape_file=AsyncMock(
            return_value=ScrapeResult(
                file_path=str(source), status=status, selected_id=123, parsed_season=1, parsed_episode=1
            )
        )
    )
    monkeypatch.setattr("server.application.history_service.HistoryService", lambda: history)
    monkeypatch.setattr(
        "server.application.scraped_file_service.ScrapedFileService",
        lambda: SimpleNamespace(register_output=AsyncMock()),
    )
    monkeypatch.setattr(
        "server.domain.system.config_service.ConfigService",
        lambda: SimpleNamespace(
            get_system_config=AsyncMock(return_value=SimpleNamespace(task_timeout=30))
        ),
    )
    monkeypatch.setattr("server.bootstrap.get_scraper_service", lambda: scraper)
    monkeypatch.setattr(scrape_module, "get_notifier", lambda: AsyncMock())
    await scrape_module._execute_scrape_job(service, job.id)
    assert scraper.scrape_file.await_args.args[0].ai_folder_context == context
    initial = history.create_record.await_args.args[0]
    assert initial.conflict_data["ai_folder_context"] == context.model_dump(mode="json")
    snapshots = [
        call.kwargs["conflict_data"]
        for call in history.update_record.await_args_list
        if "conflict_data" in call.kwargs
    ]
    assert snapshots
    if status_name == "API_FAILED":
        assert snapshots[-1]["tmdb_id"] == 123
        update = next(call.kwargs for call in history.update_record.await_args_list
                      if call.kwargs.get("conflict_data") == snapshots[-1])
        assert update["tmdb_id"] == 123
        assert update["season_number"] == 1
        assert update["episode_number"] == 1
    assert all(
        snapshot["ai_folder_context"] == context.model_dump(mode="json") for snapshot in snapshots
    )
