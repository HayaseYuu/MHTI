"""待处理批量选择与重试：按源目录分组，逐文件保留季集，不删除旧产物。"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime

from fastapi import HTTPException

from server.application.history_service import build_record_folder_path, split_record_folder_path
from server.domain.metadata.folder_context import _lexical_path
from server.domain.parsing.parser_service import ParserService
from server.models.history import HistoryConflictType, TaskStatus
from server.models.history_batch import (
    HistoryBatchGroup,
    HistoryBatchPreview,
    HistoryBatchResolveRequest,
    HistoryBatchResponse,
    HistoryBatchResult,
)
from server.models.scraper import ScrapeByIdRequest, ScrapeRequest, ScrapeStatus
from server.models.tmdb import TMDBSearchResult

logger = logging.getLogger(__name__)
_RETRYABLE = {TaskStatus.PENDING_ACTION, TaskStatus.FAILED, TaskStatus.TIMEOUT}
_SEASON_FOLDER = re.compile(
    r"^(?:season[ ._-]*\d+|s\d+|第[一二三四五六七八九十百\d]+季|specials?)$", re.I
)
_PENDING = {
    status.value: HistoryConflictType(status.value)
    for status in ScrapeStatus
    if status.value in {item.value for item in HistoryConflictType}
}


class HistoryBatchActions:
    def __init__(
        self, history_service, scrape_job_service, manual_job_service, actions, *, scraper=None
    ):
        self.history = history_service
        self.jobs = scrape_job_service
        self.manual_jobs = manual_job_service
        self.actions = actions
        self._scraper = scraper

    def scraper(self):
        if self._scraper is None:
            from server.bootstrap import get_scraper_service

            return get_scraper_service()
        return self._scraper

    async def _job(self, record):
        if not record.scrape_job_id:
            return None
        try:
            return await self.jobs.get_job(record.scrape_job_id)
        except Exception:
            logger.warning("关联刮削任务不可用，将回退到历史源路径")
            return None

    async def _identity(self, record, job):
        source, _ = split_record_folder_path(record.folder_path)
        source = getattr(job, "file_path", None) or source
        path = _lexical_path(source or "")
        if path is None or not path.is_absolute():
            return None
        folder = path.parent
        root = None
        if record.manual_job_id:
            try:
                manual = await self.manual_jobs.get_job(record.manual_job_id)
            except Exception:
                logger.warning("关联扫描任务不可用，将回退到历史目录提示")
                manual = None
            if manual:
                scan_locator = getattr(manual, "scan_locator", None)
                root = _lexical_path(scan_locator.path if scan_locator else manual.scan_path)
        if root == path:
            root = path.parent
        if root is not None and type(root) is type(path):
            try:
                parts = path.parent.relative_to(root).parts
            except ValueError:
                return None
            # 扫描根本身是作品目录时，不能把 Season 1 误当成作品。
            folder = root / parts[0] if parts and not _SEASON_FOLDER.fullmatch(parts[0]) else root
        else:
            # 未知根的 outer_folder_name 只是「最近两层的第一层」，可能是
            # /media，不能据此把 ShowA 和 ShowB 上溯合并为同一个作品。
            context = getattr(job, "ai_folder_context", None) or record.ai_folder_context
            root_name = context.scan_root_name if context else None
            matching_roots = [
                parent
                for parent in [path.parent, *path.parent.parents]
                if root_name and parent.name == root_name
            ]
            if matching_roots:
                inferred_root = matching_roots[0]
                parts = path.parent.relative_to(inferred_root).parts
                folder = (
                    inferred_root / parts[0]
                    if parts and not _SEASON_FOLDER.fullmatch(parts[0])
                    else inferred_root
                )
            elif _SEASON_FOLDER.fullmatch(folder.name):
                folder = folder.parent
        if not folder.name or folder == folder.parent:
            return None
        locator = getattr(job, "file_locator", None)
        provider = locator.provider.value if locator else "local"
        settings = getattr(job, "advanced_settings", None) or record.advanced_settings
        # 全路径避免跨库同名剧混组；内容模式不同也不能共享选择。
        identity = json.dumps(
            [provider, str(folder), bool(settings.r18) if settings else True], ensure_ascii=False
        )
        return hashlib.sha256(identity.encode()).hexdigest(), folder.name

    @staticmethod
    def _candidates(record):
        candidates = {}
        raw = (record.conflict_data or {}).get("search_results", [])
        if not isinstance(raw, list):
            return candidates
        for value in raw:
            try:
                candidate = TMDBSearchResult.model_validate(value)
            except (ValueError, TypeError):
                continue
            if candidate.id:
                candidates[candidate.id] = candidate
        return candidates

    async def preview(self, ids):
        grouped = {}
        ungrouped = []
        for record_id in dict.fromkeys(ids):
            try:
                record = await self.history.get_record(record_id)
            except Exception:
                ungrouped.append(record_id)
                continue
            if (
                record is None
                or record.status != TaskStatus.PENDING_ACTION
                or record.conflict_type != HistoryConflictType.NEED_SELECTION
            ):
                ungrouped.append(record_id)
                continue
            candidates = self._candidates(record)
            if not candidates:
                ungrouped.append(record_id)
                continue
            identity = await self._identity(record, await self._job(record))
            if not identity:
                ungrouped.append(record_id)
                continue
            key, name = identity
            if key not in grouped:
                grouped[key] = [name, [], candidates]
            group = grouped[key]
            group[1].append(record_id)
            group[2] = {key: value for key, value in group[2].items() if key in candidates}
        groups = []
        for key, (name, record_ids, candidates) in grouped.items():
            if not candidates:
                ungrouped.extend(record_ids)
            else:
                groups.append(
                    HistoryBatchGroup(
                        group_key=key,
                        folder_name=name,
                        record_ids=record_ids,
                        candidates=list(candidates.values()),
                    )
                )
        return HistoryBatchPreview(groups=groups, ungrouped_ids=ungrouped)

    async def resolve(self, request: HistoryBatchResolveRequest):
        preview = await self.preview(request.record_ids)
        group = next(
            (
                group
                for group in preview.groups
                if group.group_key == request.group_key
                and set(group.record_ids) == set(request.record_ids)
            ),
            None,
        )
        if (
            preview.ungrouped_ids
            or group is None
            or request.tmdb_id not in {candidate.id for candidate in group.candidates}
        ):
            raise HTTPException(
                status_code=400, detail="所选记录已变化、目录不同或版本不在共有候选中，请刷新后重试"
            )
        return await self._batch(
            request.record_ids,
            selected_id=request.tmdb_id,
            season=request.season,
            group_key=request.group_key,
        )

    async def retry(self, ids):
        return await self._batch(ids)

    async def _batch(self, ids, **kwargs):
        results = []
        # 限制并发为一：避免一次操作放大 API 故障，并允许前端逐条提交显示进度。
        for record_id in dict.fromkeys(ids):
            try:
                results.append(await self._execute(record_id, **kwargs))
            except Exception as exc:
                logger.warning("批量单项预检查失败 %s (%s)", record_id, type(exc).__name__)
                results.append(self._result(record_id, None, "记录读取或校验失败，请稍后重试"))
        success = sum(item.success for item in results)
        return HistoryBatchResponse(
            results=results, success_count=success, failed_count=len(results) - success
        )

    def _result(self, record_id, status, message, *, success=False):
        return HistoryBatchResult(
            record_id=record_id, status=status, success=success, message=message or "处理完成"
        )

    async def _execute(self, record_id, *, selected_id=None, season=None, group_key=None):
        record = await self.history.get_record(record_id)
        if record is None:
            return self._result(record_id, None, "记录不存在")
        if record.status not in _RETRYABLE:
            return self._result(record_id, record.status, "仅待处理、失败和超时记录可重试")
        if selected_id is not None:
            job = await self._job(record)
            identity = await self._identity(record, job)
            if (
                record.status != TaskStatus.PENDING_ACTION
                or record.conflict_type != HistoryConflictType.NEED_SELECTION
                or not identity
                or identity[0] != group_key
                or selected_id not in self._candidates(record)
            ):
                return self._result(record_id, record.status, "记录或候选已变化，请刷新后重试")
        started = datetime.now()
        claimed = False
        try:
            if not await self.history.claim_for_retry(record_id, {record.status}):
                current = await self.history.get_record(record_id)
                return self._result(
                    record_id, current.status if current else None, "该记录正在处理中或已变化"
                )
            claimed = True
            return await self._run_claimed(record, started, selected_id=selected_id, season=season)
        except asyncio.CancelledError:
            if not claimed:
                raise
            await self.history.update_record(
                record_id, status=TaskStatus.FAILED, error_message="批量操作已中断，可重新重试"
            )
            raise
        except TimeoutError:
            if not claimed:
                return self._result(record_id, record.status, "领取记录超时，请稍后重试")
            await self.history.update_record(
                record_id,
                status=TaskStatus.TIMEOUT,
                error_message="重试超时，可稍后再次重试",
                duration_seconds=(datetime.now() - started).total_seconds(),
            )
            return self._result(record_id, TaskStatus.TIMEOUT, "重试超时，可稍后再次重试")
        except Exception as exc:
            if not claimed:
                logger.warning("领取批量记录失败 %s (%s)", record_id, type(exc).__name__)
                return self._result(record_id, record.status, "领取记录失败，请稍后重试")
            message = (
                str(exc.detail)
                if isinstance(exc, HTTPException)
                else "重试失败，请查看刮削日志或稍后重试"
            )
            logger.warning("批量刮削单项失败 %s (%s)", record_id, type(exc).__name__)
            await self.history.update_record(
                record_id,
                status=TaskStatus.FAILED,
                error_message=message,
                duration_seconds=(datetime.now() - started).total_seconds(),
            )
            return self._result(record_id, TaskStatus.FAILED, message)

    async def _run_claimed(self, record, started, *, selected_id, season):
        job = await self._job(record)
        context = dict(record.conflict_data or {})
        source, _ = split_record_folder_path(record.folder_path)
        source = getattr(job, "file_path", None) or source
        if not source:
            raise HTTPException(status_code=400, detail="记录缺少源文件路径")
        locators = await self.actions.restore_locators(record)
        kwargs = dict(
            file_path=source,
            output_dir=context.get("output_dir"),
            metadata_dir=context.get("metadata_dir"),
            link_mode=context.get("link_mode"),
            **locators,
        )
        kwargs.setdefault("advanced_settings", record.advanced_settings)
        kwargs.setdefault("ai_folder_context", record.ai_folder_context)
        request = ScrapeRequest(**kwargs)
        await self.actions.fill_organize_params(record, request)
        scraper = self.scraper()
        lexical_source = _lexical_path(source)
        if lexical_source is None:
            raise HTTPException(status_code=400, detail="源文件路径无效")
        parsed = ParserService().parse(lexical_source.name, source)
        # 用户批量选择只改变作品版本，每个文件沿用自己的普通解析季集。
        known_id = (
            selected_id or context.get("batch_selected_id") or context.get("match_resolved_id")
        )
        if known_id is None and record.conflict_type != HistoryConflictType.NEED_SELECTION:
            known_id = context.get("tmdb_id") or record.tmdb_id
        parsed_season = context.get("parsed_season")
        parsed_episode = context.get("parsed_episode")
        # 旧版冲突把已核验季集放在 season/episode，旧超时只写记录列。
        # 换作品的新批量选择不读取旧作品的记录季集，但始终保留当前文件解析快照。
        if selected_id is None and known_id is not None:
            if parsed_season is None:
                parsed_season = context.get("season")
                if parsed_season is None:
                    parsed_season = record.season_number
            if parsed_episode is None:
                parsed_episode = context.get("episode")
                if parsed_episode is None:
                    parsed_episode = record.episode_number
        parsed_season = (
            parsed_season if type(parsed_season) is int and parsed_season >= 0 else parsed.season
        )
        parsed_episode = (
            parsed_episode if type(parsed_episode) is int and parsed_episode > 0 else parsed.episode
        )
        if selected_id is not None:
            context["batch_selected_id"] = selected_id
            context["tmdb_id"] = selected_id
            await self.history.update_record(record.id, conflict_data=context, tmdb_id=selected_id)
        actual_season = season if selected_id is not None and season is not None else parsed_season
        if known_id is not None and (actual_season is None or parsed_episode is None):
            context.update(
                tmdb_id=known_id, parsed_season=actual_season, parsed_episode=parsed_episode
            )
            await self.history.update_record(
                record.id,
                status=TaskStatus.PENDING_ACTION,
                conflict_type=HistoryConflictType.NEED_SEASON_EPISODE,
                conflict_data=context,
                error_message="版本已选择，此文件仍需确认季/集号",
            )
            return self._result(
                record.id, TaskStatus.PENDING_ACTION, "版本已选择，此文件仍需确认季/集号"
            )
        existing_logs = list(record.scrape_logs or [])

        async def on_log_update(logs):
            await self.history.update_scrape_logs(record.id, existing_logs + logs)

        async def on_match_resolved(tmdb_id, resolved_season, resolved_episode):
            context.update(
                match_resolved_id=tmdb_id,
                tmdb_id=tmdb_id,
                parsed_season=resolved_season,
                parsed_episode=resolved_episode,
            )
            await self.history.update_record(
                record.id,
                conflict_data=context,
                tmdb_id=tmdb_id,
                season_number=resolved_season,
                episode_number=resolved_episode,
            )

        timeout = 300
        config_service = getattr(scraper, "config_service", None)
        if config_service:
            config = await config_service.get_system_config()
            timeout = config.task_timeout
        if known_id is not None:
            explicit = ScrapeByIdRequest(
                **request.model_dump(exclude={"auto_select"}),
                tmdb_id=known_id,
                season=actual_season,
                episode=parsed_episode,
            )
            operation = scraper.scrape_by_id(explicit, on_log_update=on_log_update)
        else:
            operation = scraper.scrape_file(
                request, on_log_update=on_log_update, on_match_resolved=on_match_resolved
            )
        result = await asyncio.wait_for(operation, timeout=timeout)
        duration = (datetime.now() - started).total_seconds()
        if result.status == ScrapeStatus.SUCCESS:
            await self.actions._finalize(
                record.id,
                result,
                manual_job_id=record.manual_job_id,
                duration_seconds=duration,
                folder_path=build_record_folder_path(source, result.dest_path),
            )
            return self._result(record.id, TaskStatus.SUCCESS, "处理成功", success=True)
        # 新冲突要完整保存，不能被普通重试入口误压成 failed 或遗失候选。
        context.update(
            output_dir=request.output_dir,
            metadata_dir=request.metadata_dir,
            link_mode=request.link_mode.value if request.link_mode else None,
            advanced_settings=request.advanced_settings.model_dump()
            if request.advanced_settings
            else None,
            ai_folder_context=request.ai_folder_context.model_dump()
            if request.ai_folder_context
            else None,
        )
        context.update(
            parsed_season=result.parsed_season,
            parsed_episode=result.parsed_episode,
            season=result.parsed_season,
            episode=result.parsed_episode,
        )
        if result.selected_id is not None:
            context["tmdb_id"] = result.selected_id
        if result.search_results is not None:
            context["search_results"] = [
                item.model_dump(mode="json") for item in result.search_results
            ]
        if result.series_info is not None:
            context["series_info"] = result.series_info.model_dump(mode="json")
        if result.status == ScrapeStatus.EMBY_CONFLICT:
            context["emby_message"] = result.message
        if result.emby_conflict is not None:
            context["emby_conflict"] = result.emby_conflict.model_dump(mode="json")
        context["dest_path"] = result.dest_path
        conflict_type = _PENDING.get(result.status.value)
        status = TaskStatus.PENDING_ACTION if conflict_type else TaskStatus.FAILED
        await self.history.update_record(
            record.id,
            status=status,
            conflict_type=conflict_type,
            conflict_data=context,
            error_message=result.message or "刮削未完成",
            duration_seconds=duration,
            tmdb_id=result.selected_id,
            season_number=result.parsed_season,
            episode_number=result.parsed_episode,
        )
        return self._result(record.id, status, result.message)
