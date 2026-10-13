"""TMDB API endpoints for search and metadata retrieval.

异常处理：所有 TMDBError 子类（TMDBNotConfiguredError、TMDBTimeoutError、
TMDBConnectionError、TMDBNotFoundError）由全局异常处理器统一处理。
"""

import logging

from fastapi import APIRouter, Depends, Query

from server.api.deps import get_tmdb_service, require_auth
from server.common.exceptions import TMDBNotFoundError
from server.domain.metadata.anime_metadata_service import AnimeMetadataService
from server.domain.metadata.tmdb_service import TMDBService
from server.models.tmdb import (
    TMDBError,
    TMDBSearchResponse,
    TMDBSeason,
    TMDBSeries,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tmdb", tags=["tmdb"], dependencies=[Depends(require_auth)])


@router.get(
    "/search",
    response_model=TMDBSearchResponse,
    responses={
        400: {"model": TMDBError, "description": "API Token not configured"},
        408: {"model": TMDBError, "description": "Request timeout"},
        502: {"model": TMDBError, "description": "TMDB connection error"},
    },
)
async def search_tv(
    q: str = Query(..., min_length=1, description="Search query"),
    language: str = Query("zh-CN", description="Language for results"),
    r18: bool = Query(False, description="R18 成人模式；关闭时使用表番双数据源"),
    tmdb_service: TMDBService = Depends(get_tmdb_service),
) -> TMDBSearchResponse:
    """
    Search for TV series on TMDB.

    Args:
        q: Search query string
        language: Language for results (default: zh-CN)

    Returns:
        Search results with matching TV series.

    Raises:
        TMDBNotConfiguredError: API Token 未配置 (400)
        TMDBTimeoutError: 请求超时 (408)
        TMDBConnectionError: 连接失败 (502)
    """
    if not r18:
        return await AnimeMetadataService(tmdb_service).search_series_by_api(q, language)
    response = await tmdb_service.search_series_by_api(q, language, include_adult=True)
    response.results = [item for item in response.results if item.adult]
    response.total_results = len(response.results)
    return response


@router.get(
    "/series/{tmdb_id}",
    response_model=TMDBSeries,
    responses={
        404: {"model": TMDBError, "description": "Series not found"},
        408: {"model": TMDBError, "description": "Request timeout"},
        502: {"model": TMDBError, "description": "TMDB connection error"},
    },
)
async def get_series(
    tmdb_id: int,
    language: str = Query("zh-CN", description="Language for metadata"),
    include_episodes: bool = Query(True, description="Include episode details for each season"),
    r18: bool = Query(False, description="R18 成人模式；关闭时使用表番双数据源"),
    tmdb_service: TMDBService = Depends(get_tmdb_service),
) -> TMDBSeries:
    """
    Get TV series details from TMDB.

    Args:
        tmdb_id: TMDB series ID
        language: Language for metadata (default: zh-CN)
        include_episodes: Whether to include episode details (default: True)

    Returns:
        Complete series information including seasons and episodes.

    Raises:
        TMDBNotFoundError: 剧集未找到 (404)
        TMDBTimeoutError: 请求超时 (408)
        TMDBConnectionError: 连接失败 (502)
    """
    provider = tmdb_service if r18 else AnimeMetadataService(tmdb_service)
    if r18 and tmdb_id <= 0:
        raise TMDBNotFoundError("当前内容模式的剧集", tmdb_id)
    series = await provider.get_series_by_api(tmdb_id, language)
    if series is None or series.adult != r18:
        raise TMDBNotFoundError("当前内容模式的剧集", tmdb_id)
    if include_episodes:
        for index, season in enumerate(series.seasons):
            if season.episodes is not None or season.season_number == 0:
                continue
            try:
                details = await provider.get_season_by_api(tmdb_id, season.season_number, language)
                if details is not None:
                    series.seasons[index] = details
            except Exception:
                # 单季不可用仍保留整体详情，用户可在手选季度时重试。
                logger.warning("季度 %s 详情不可用，保留基础元数据", season.season_number)
    return series


@router.get(
    "/series/{tmdb_id}/season/{season_number}",
    response_model=TMDBSeason,
    responses={
        404: {"model": TMDBError, "description": "Season not found"},
        408: {"model": TMDBError, "description": "Request timeout"},
        502: {"model": TMDBError, "description": "TMDB connection error"},
    },
)
async def get_season(
    tmdb_id: int,
    season_number: int,
    language: str = Query("zh-CN", description="Language for metadata"),
    r18: bool = Query(False, description="R18 成人模式；关闭时使用表番双数据源"),
    tmdb_service: TMDBService = Depends(get_tmdb_service),
) -> TMDBSeason:
    """
    Get season details including episodes.

    Args:
        tmdb_id: TMDB series ID
        season_number: Season number
        language: Language for metadata (default: zh-CN)

    Returns:
        Season information with episode list.

    Raises:
        TMDBNotFoundError: 季未找到 (404)
        TMDBTimeoutError: 请求超时 (408)
        TMDBConnectionError: 连接失败 (502)
    """
    provider = tmdb_service if r18 else AnimeMetadataService(tmdb_service)
    if r18 and tmdb_id <= 0:
        raise TMDBNotFoundError("当前内容模式的剧集", tmdb_id)
    series = await provider.get_series_by_api(tmdb_id, language)
    if series is None or series.adult != r18:
        raise TMDBNotFoundError("当前内容模式的剧集", tmdb_id)
    season = await provider.get_season_by_api(tmdb_id, season_number, language)
    if season is None:
        raise TMDBNotFoundError("季", f"{tmdb_id}/{season_number}")
    return season
