"""AI 仅辅助普通刮削的编排边界回归；全部使用本地假服务。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import httpx
import pytest

from server.domain.metadata.anilist_service import AniListError
from server.models.ai import AISuggestion
from server.models.manual_job import ManualJobAdvancedSettings
from server.models.organize import OrganizeMode
from server.models.parser import ParsedInfo
from server.models.scraper import (
    BatchScrapeRequest,
    ScrapeByIdRequest,
    ScrapeRequest,
    ScrapeStatus,
)
from server.models.tmdb import TMDBSearchResponse, TMDBSearchResult
from server.tests.application.test_anime_scraping import _service


def _response(*items, query="test"):
    return TMDBSearchResponse(query=query, results=list(items), total_results=len(items))


def _candidate(id=-7, adult=False):
    return TMDBSearchResult(
        id=id, name=f"Title {id}", adult=adult, metadata_source="anilist" if id < 0 else "tmdb"
    )


def _identified(title="Test Show", confidence=0.95):
    return AISuggestion(
        action="identify_title",
        title=title,
        confidence=confidence,
        reason="untrusted-private-reason",
    )


def _selected(id=-7, confidence=0.95):
    return AISuggestion(
        action="select_candidate",
        selected_id=id,
        confidence=confidence,
        reason="untrusted-private-reason",
    )


@pytest.fixture
def case(temp_db, tmp_path, monkeypatch):
    service, adult, anime = _service(temp_db, monkeypatch)
    ai = SimpleNamespace(
        is_enabled=AsyncMock(return_value=True),
        identify_title=AsyncMock(return_value=None),
        select_candidate=AsyncMock(return_value=None),
    )
    service.ai_assist_service = ai
    source = tmp_path / "Test.Show.S01E01.mp4"
    source.write_bytes(b"video")
    request = ScrapeRequest(
        file_path=str(source), output_dir=str(tmp_path / "library"), link_mode=OrganizeMode.COPY
    )
    return service, adult, anime, ai, request


def _assert_no_ai(ai):
    ai.is_enabled.assert_not_awaited()
    ai.identify_title.assert_not_awaited()
    ai.select_candidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_normal_match_never_calls_ai(case):
    service, _, anime, ai, request = case
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.SUCCESS
    assert result.selected_id == -7
    anime.get_series_by_api.assert_awaited_once_with(-7)
    _assert_no_ai(ai)
    assert "AI 辅助识别" not in [step.name for step in result.scrape_logs]


@pytest.mark.asyncio
@pytest.mark.parametrize("global_disabled", [False, True])
async def test_disabled_ai_keeps_manual_selection(case, global_disabled):
    service, _, anime, ai, request = case
    anime.search_series_by_api.return_value = _response(_candidate(-8), _candidate(-7))
    if global_disabled:
        ai.is_enabled.return_value = False
    else:
        request.advanced_settings = ManualJobAdvancedSettings(ai_assist=False)
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NEED_SELECTION
    assert result.dest_path is None
    ai.identify_title.assert_not_awaited()
    ai.select_candidate.assert_not_awaited()
    assert "AI 辅助识别" not in [step.name for step in result.scrape_logs]
    if not global_disabled:
        ai.is_enabled.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_negative_anilist_id_is_only_advice(case):
    service, _, anime, ai, request = case
    candidates = [_candidate(-8), _candidate(-7)]
    anime.search_series_by_api.return_value = _response(*candidates)
    ai.select_candidate.return_value = _selected()
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.SUCCESS
    assert result.selected_id == -7
    anime.get_series_by_api.assert_awaited_once_with(-7)
    anime.get_season_by_api.assert_awaited_once_with(-7, 1)
    ai.identify_title.assert_not_awaited()
    ai.select_candidate.assert_awaited_once_with("Test.Show.S01E01.mp4", "Test Show", candidates)
    assert any(
        "继续普通刮削核验" in log.message for step in result.scrape_logs for log in step.logs
    )
    assert all(
        "untrusted-private-reason" not in log.message
        for step in result.scrape_logs
        for log in step.logs
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "suggestion",
    [
        _selected(-7, 0.79),
        _selected(-999),
        None,
        SimpleNamespace(action="select_candidate", selected_id=True, confidence=0.99),
        SimpleNamespace(action="select_candidate", selected_id=-7, confidence=float("nan")),
        _identified(),
    ],
)
async def test_unsafe_candidate_advice_cannot_move_or_select(case, suggestion):
    service, _, anime, ai, request = case
    anime.search_series_by_api.return_value = _response(_candidate(-8), _candidate(-7))
    ai.select_candidate.return_value = suggestion
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NEED_SELECTION
    assert result.selected_id is None
    assert result.dest_path is None
    anime.get_series_by_api.assert_not_awaited()
    assert all(step.completed for step in result.scrape_logs if step.name == "AI 辅助识别")


@pytest.mark.asyncio
async def test_missing_title_ai_preserves_original_season_episode_year(case):
    service, _, anime, ai, request = case
    parsed = ParsedInfo(original_filename="opaque.mp4", season=3, episode=4, year=2021)
    service.parser_service = Mock(parse=Mock(return_value=parsed))
    ai.identify_title.return_value = _identified()
    # 保留原季集后，由普通核验阻止不存在的季集，不允许 AI 改成 S01E01。
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NEED_SEASON_EPISODE
    assert (result.parsed_title, result.parsed_season, result.parsed_episode) == ("Test Show", 3, 4)
    assert parsed.series_name is None
    assert parsed.year == 2021
    assert result.dest_path is None
    anime.search_series_by_api.assert_awaited_once_with("Test Show")
    ai.identify_title.assert_awaited_once_with("Test.Show.S01E01.mp4", None)
    ai.select_candidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_matching_result_researches_corrected_title_once(case):
    service, _, anime, ai, request = case
    anime.search_series_by_api.side_effect = [_response(), _response(_candidate())]
    ai.identify_title.return_value = _identified("Corrected Show")
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.SUCCESS
    assert result.parsed_title == "Corrected Show"
    assert anime.search_series_by_api.await_args_list == [call("Test Show"), call("Corrected Show")]
    ai.identify_title.assert_awaited_once_with("Test.Show.S01E01.mp4", "Test Show")
    ai.select_candidate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "suggestion", [_identified("Test Show"), _identified(confidence=0.79), None]
)
async def test_ineffective_title_does_not_repeat_search(case, suggestion):
    service, _, anime, ai, request = case
    anime.search_series_by_api.return_value = _response()
    ai.identify_title.return_value = suggestion
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NO_MATCH
    assert result.parsed_title == "Test Show"
    anime.search_series_by_api.assert_awaited_once_with("Test Show")
    ai.identify_title.assert_awaited_once()
    ai.select_candidate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_at_most_one_title_and_one_selection_attempt_per_file(case, missing):
    service, _, anime, ai, request = case
    if missing:
        service.parser_service = Mock(
            parse=Mock(return_value=ParsedInfo(original_filename="opaque.mp4", season=1, episode=1))
        )
        anime.search_series_by_api.return_value = _response(_candidate(-8), _candidate(-7))
    else:
        anime.search_series_by_api.side_effect = [
            _response(),
            _response(_candidate(-8), _candidate(-7)),
        ]
    ai.identify_title.return_value = _identified("Corrected Show")
    ai.select_candidate.return_value = _selected()
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.SUCCESS
    assert ai.identify_title.await_count + ai.select_candidate.await_count == 2
    assert anime.search_series_by_api.await_count == (1 if missing else 2)


@pytest.mark.asyncio
async def test_title_retry_no_results_does_not_loop(case):
    service, _, anime, ai, request = case
    anime.search_series_by_api.return_value = _response()
    ai.identify_title.return_value = _identified("Corrected Show")
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NO_MATCH
    assert anime.search_series_by_api.await_count == 2
    ai.identify_title.assert_awaited_once()
    ai.select_candidate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("r18", [False, True])
async def test_ai_cannot_select_cross_mode_id(case, r18):
    service, adult, anime, ai, request = case
    request.advanced_settings = ManualJobAdvancedSettings(r18=r18)
    candidates = [_candidate(-7), _candidate(-8), _candidate(123, True), _candidate(124, True)]
    (adult if r18 else anime).search_series_by_api.return_value = _response(*candidates)
    ai.select_candidate.return_value = _selected(-7 if r18 else 123)
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NEED_SELECTION
    sent_candidates = ai.select_candidate.call_args.args[2]
    assert len(sent_candidates) == 2
    assert all(item.adult == r18 for item in sent_candidates)
    assert result.selected_id is None
    assert result.dest_path is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.TimeoutException("timeout"),
        httpx.RequestError("offline"),
        AniListError("unauthorized"),
        ValueError("missing token"),
    ],
)
async def test_metadata_search_failure_is_not_an_ai_trigger(case, error):
    service, _, anime, ai, request = case
    anime.search_series_by_api.side_effect = error
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.SEARCH_FAILED
    _assert_no_ai(ai)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["identify_title", "select_candidate", "is_enabled"])
async def test_ai_failure_preserves_original_outcome_without_secret_logs(case, stage):
    service, _, anime, ai, request = case
    anime.search_series_by_api.return_value = (
        _response(_candidate(-8), _candidate(-7)) if stage == "select_candidate" else _response()
    )
    getattr(ai, stage).side_effect = RuntimeError("sk-private-must-never-be-logged")
    result = await service.scrape_file(request)
    assert result.status == (
        ScrapeStatus.NEED_SELECTION if stage == "select_candidate" else ScrapeStatus.NO_MATCH
    )
    assert result.dest_path is None
    assert all("sk-private" not in log.message for step in result.scrape_logs for log in step.logs)


@pytest.mark.asyncio
async def test_manual_selection_flag_does_not_let_ai_choose_candidate(case):
    service, _, anime, ai, request = case
    request.auto_select = False
    anime.search_series_by_api.return_value = _response(_candidate(-8), _candidate(-7))
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NEED_SELECTION
    assert result.selected_id is None
    _assert_no_ai(ai)


@pytest.mark.asyncio
async def test_explicit_id_preview_and_dry_run_never_call_ai(case):
    service, _, anime, ai, request = case
    anime.search_series_by_api.return_value = _response(_candidate(-8), _candidate(-7))
    manual = await service.scrape_by_id(
        ScrapeByIdRequest(
            file_path=request.file_path,
            tmdb_id=-7,
            season=1,
            episode=1,
            link_mode=OrganizeMode.COPY,
            output_dir=request.output_dir,
        )
    )
    assert manual.status == ScrapeStatus.SUCCESS
    await service.preview(request.file_path)
    await service.batch_scrape(BatchScrapeRequest(file_paths=[request.file_path], dry_run=True))
    _assert_no_ai(ai)


@pytest.mark.asyncio
async def test_missing_file_never_calls_ai(case):
    service, _, _, ai, request = case
    request.file_path += ".missing"
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.MOVE_FAILED
    _assert_no_ai(ai)


@pytest.mark.asyncio
async def test_season_verification_and_conflicts_do_not_trigger_ai(case):
    service, _, anime, ai, request = case
    anime.get_season_by_api.return_value = None
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NEED_SEASON_EPISODE
    _assert_no_ai(ai)


@pytest.mark.asyncio
async def test_concurrent_files_have_independent_two_call_budgets(case):
    service, _, anime, ai, request = case
    query_counts = {}

    async def search(query):
        await asyncio.sleep(0)
        query_counts[query] = query_counts.get(query, 0) + 1
        return _response() if query == "Test Show" else _response(_candidate(-8), _candidate(-7))

    anime.search_series_by_api.side_effect = search
    ai.identify_title.return_value = _identified("Corrected Show")
    ai.select_candidate.return_value = _selected()
    # 人工整理不参与本测试，避免两个并发输出覆盖同一个目的文件。
    service._move_and_finalize = AsyncMock(side_effect=lambda **kw: kw["result"])
    results = await asyncio.gather(service.scrape_file(request), service.scrape_file(request))
    assert all(
        result.status == ScrapeStatus.SUCCESS and result.selected_id == -7 for result in results
    )
    assert query_counts == {"Test Show": 2, "Corrected Show": 2}
    assert ai.identify_title.await_count == 2
    assert ai.select_candidate.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["details", "emby", "file_conflict"])
async def test_non_identification_failures_do_not_trigger_ai(case, stage):
    from server.models.emby import ConflictCheckResult, ConflictType

    service, _, anime, ai, request = case
    if stage == "details":
        anime.get_series_by_api.side_effect = httpx.TimeoutException("timeout")
        expected = ScrapeStatus.API_FAILED
    elif stage == "emby":
        service._check_emby_conflict.return_value = ConflictCheckResult(
            conflict_type=ConflictType.EPISODE_EXISTS, message="already exists"
        )
        expected = ScrapeStatus.EMBY_CONFLICT
    else:
        first = await service.scrape_file(request)
        assert first.status == ScrapeStatus.SUCCESS
        expected = ScrapeStatus.FILE_CONFLICT
    result = await service.scrape_file(request)
    assert result.status == expected
    _assert_no_ai(ai)


@pytest.mark.asyncio
async def test_missing_title_search_empty_does_not_identify_a_second_time(case):
    service, _, anime, ai, request = case
    service.parser_service = Mock(
        parse=Mock(return_value=ParsedInfo(original_filename="opaque.mp4", season=1, episode=1))
    )
    anime.search_series_by_api.return_value = _response()
    ai.identify_title.return_value = _identified("Corrected Show")
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NO_MATCH
    anime.search_series_by_api.assert_awaited_once_with("Corrected Show")
    ai.identify_title.assert_awaited_once()
    ai.select_candidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_selected_candidate_still_requires_provider_content_verification(case):
    service, _, anime, ai, request = case
    anime.search_series_by_api.return_value = _response(_candidate(-8), _candidate(-7))
    ai.select_candidate.return_value = _selected()
    anime.get_series_by_api.return_value = anime.get_series_by_api.return_value.model_copy(
        update={"adult": True}
    )
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.API_FAILED
    assert "模式不一致" in result.message
    assert result.dest_path is None
    anime.get_season_by_api.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_title", [False, True])
async def test_manual_mode_never_identifies_title(case, missing_title):
    service, _, anime, ai, request = case
    request.auto_select = False
    anime.search_series_by_api.return_value = _response()
    if missing_title:
        service.parser_service = Mock(
            parse=Mock(return_value=ParsedInfo(original_filename="opaque.mp4", season=1, episode=1))
        )
    result = await service.scrape_file(request)
    assert result.status == ScrapeStatus.NO_MATCH
    _assert_no_ai(ai)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 1, 2])
async def test_incomplete_search_does_not_trigger_ai(case, count):
    service, _, anime, ai, request = case
    response = _response(*[_candidate(-7 - index) for index in range(count)])
    response.search_complete = False
    anime.search_series_by_api.return_value = response
    result = await service.scrape_file(request)
    expected = [ScrapeStatus.SEARCH_FAILED, ScrapeStatus.SUCCESS, ScrapeStatus.NEED_SELECTION]
    assert result.status == expected[count]
    _assert_no_ai(ai)
    if count == 0:
        assert "搜索不完整" in result.message
