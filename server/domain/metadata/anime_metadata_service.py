"""表番双源聚合：TMDB 为季集权威，AniList 提供动画补全及独立回退。"""

import asyncio
import logging
import unicodedata

from server.common.exceptions import TMDBNotConfiguredError
from server.domain.metadata.anilist_service import AniListService
from server.domain.metadata.tmdb_service import TMDBService
from server.models.tmdb import TMDBSearchResponse, TMDBSearchResult, TMDBSeason, TMDBSeries

logger = logging.getLogger(__name__)


def _normalize_title(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


class AnimeMetadataService:
    def __init__(self, tmdb_service: TMDBService, config_service=None):
        self.tmdb_service = tmdb_service
        self.config_service = config_service or getattr(tmdb_service, "config_service", None)
        self.anilist_service = AniListService(self.config_service)

    async def _language(self, language: str | None) -> str:
        if language is not None:
            return language
        if self.config_service is None:
            return "zh-CN"
        config = await self.config_service.get_language_config()
        return config.primary

    @staticmethod
    def _matches(item: TMDBSearchResult | TMDBSeries, media: dict) -> bool:
        # 缺乏日期或仅有近似标题时保留两条候选，不强行合并不同季度。
        start = media.get("startDate") or {}
        if not item.first_air_date or item.first_air_date.year != start.get("year"):
            return False
        tmdb_titles = {_normalize_title(t) for t in (item.name, item.original_name) if t}
        anime_titles = {_normalize_title(t) for t in AniListService.titles(media)}
        return bool((tmdb_titles - {""}) & (anime_titles - {""}))

    def _enrich(self, item: TMDBSearchResult | TMDBSeries, media: dict, language: str | None):
        anime = self.anilist_service.to_series(media, language)
        item = item.model_copy(deep=True)
        item.anilist_id = media["id"]
        # 不覆盖 TMDB 的年份、季数、集数、标题；这些字段决定文件命名与集映射。
        for field in ("overview", "poster_path", "vote_average"):
            if getattr(item, field) is None or getattr(item, field) == "":
                setattr(item, field, getattr(anime, field))
        if isinstance(item, TMDBSeries):
            item.backdrop_path = item.backdrop_path or anime.backdrop_path
            item.genres = list(dict.fromkeys([*item.genres, *anime.genres]))
        return item

    async def search_series_by_api(
        self,
        query: str,
        language: str | None = None,
    ) -> TMDBSearchResponse:
        language = await self._language(language)
        if not query.strip():
            return TMDBSearchResponse(query=query, total_results=0, results=[])
        tmdb, anime = await asyncio.gather(
            self.tmdb_service.search_series_by_api(query, language, include_adult=False),
            self.anilist_service.search(query),
            return_exceptions=True,
        )
        if isinstance(tmdb, Exception) and isinstance(anime, Exception):
            raise anime
        results = [] if isinstance(tmdb, Exception) else [r for r in tmdb.results if not r.adult]
        media_list = [] if isinstance(anime, Exception) else anime
        results = [
            r for r in results if 16 in r.genre_ids or any(self._matches(r, m) for m in media_list)
        ]
        used = set()
        for index, item in enumerate(results):
            matches = [m for m in media_list if self._matches(item, m)]
            # 同标题同年仍可能存在多个版本，歧义时不绑定 AniList ID。
            if (
                len(matches) == 1
                and sum(self._matches(other, matches[0]) for other in results) == 1
            ):
                results[index] = self._enrich(item, matches[0], language)
                used.add(matches[0]["id"])
        results.extend(
            self.anilist_service.to_search_result(media, language)
            for media in media_list
            if media["id"] not in used
        )
        # 未配置 TMDB 是允许的 AniList 单源模式；网络/鉴权/限流异常则禁止 AI 补猜。
        complete = not isinstance(anime, Exception) and (
            not isinstance(tmdb, Exception) or isinstance(tmdb, TMDBNotConfiguredError)
        )
        return TMDBSearchResponse(
            query=query, total_results=len(results), results=results, search_complete=complete
        )

    async def get_series_by_api(
        self,
        tmdb_id: int,
        language: str | None = None,
    ) -> TMDBSeries | None:
        language = await self._language(language)
        if tmdb_id < 0:
            media = await self.anilist_service.get_media(-tmdb_id)
            return self.anilist_service.to_series(media, language) if media else None
        if tmdb_id == 0:
            return None
        series = await self.tmdb_service.get_series_by_api(tmdb_id, language)
        if series is None or series.adult:
            return None
        try:
            media = await self.anilist_service.search(series.original_name or series.name)
            matches = [m for m in media if self._matches(series, m)]
            if len(matches) == 1:
                series = self._enrich(series, matches[0], language)
            elif 16 not in series.genre_ids:
                return None
        except Exception:
            logger.warning("AniList 补全不可用，保留 TMDB 元数据", exc_info=True)
            if 16 not in series.genre_ids:
                return None
        return series

    async def get_season_by_api(
        self,
        tmdb_id: int,
        season_number: int,
        language: str | None = None,
    ) -> TMDBSeason | None:
        language = await self._language(language)
        if tmdb_id < 0:
            if season_number != 1:
                return None
            media = await self.anilist_service.get_media(-tmdb_id)
            return self.anilist_service.to_season(media, language) if media else None
        # TMDB 的跨季结构不能用 AniList 单季度结构代替。
        return await self.tmdb_service.get_season_by_api(tmdb_id, season_number, language)
