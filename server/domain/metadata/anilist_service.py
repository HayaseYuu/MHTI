"""AniList 公共动画元数据客户端；不需要 API Token。"""

import html
import re
from datetime import date
from typing import Any

import httpx

from server.common.exceptions import AppException, ErrorCode
from server.domain.system.config_service import ConfigService
from server.models.tmdb import TMDBEpisode, TMDBSearchResult, TMDBSeason, TMDBSeries

ANILIST_API_URL = "https://graphql.anilist.co"
# 单次响应与生成占位集数都有边界，不缓存远端响应。
MAX_RESULTS = 20
MAX_EPISODES = 5000
MEDIA_FIELDS = """
    id type format isAdult title { romaji english native }
    synonyms description(asHtml: false) startDate { year month day }
    episodes duration averageScore genres status
    coverImage { extraLarge large } bannerImage
"""
SEARCH_QUERY = (
    """
query ($search: String!, $perPage: Int!) {
  Page(page: 1, perPage: $perPage) {
    media(search: $search, type: ANIME, isAdult: false) { %s }
  }
}
"""
    % MEDIA_FIELDS
)
DETAIL_QUERY = (
    """
query ($id: Int!) { Media(id: $id, type: ANIME, isAdult: false) { %s } }
"""
    % MEDIA_FIELDS
)


class AniListError(AppException):
    """AniList 可解释的上游错误，交由现有全局异常处理器返回。"""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(
            message, ErrorCode.SCRAPE_SEARCH_FAILED, {"source": "anilist"}, status_code=status_code
        )


class AniListService:
    def __init__(self, config_service: ConfigService):
        self.config_service = config_service

    async def _request(self, query: str, variables: dict) -> dict:
        config = await self.config_service.get_system_config()
        proxy = await self.config_service.get_proxy_config()
        try:
            async with httpx.AsyncClient(
                timeout=float(config.task_timeout), proxy=proxy.get_url()
            ) as client:
                response = await client.post(
                    ANILIST_API_URL,
                    json={"query": query, "variables": variables},
                    headers={"Accept": "application/json"},
                )
            # 429 不自动重试，避免连续任务把限流扩大为请求风暴。
            if response.status_code == 429:
                raise AniListError("AniList 请求频率受限，请稍后重试", status_code=429)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("errors"):
                raise AniListError("AniList GraphQL 请求失败")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise AniListError("AniList 返回的数据格式无效")
            return data
        except httpx.TimeoutException as exc:
            raise AniListError("AniList 请求超时", status_code=408) from exc
        except (httpx.HTTPError, ValueError, ImportError) as exc:
            raise AniListError("AniList 连接或响应异常") from exc

    @staticmethod
    def is_safe_anime(media: Any) -> bool:
        # 不信任仅由查询条件过滤的结果；adult 缺失时也不能判定为表番。
        return (
            isinstance(media, dict)
            and isinstance(media.get("id"), int)
            and media["id"] > 0
            and media.get("type") == "ANIME"
            and media.get("isAdult") is False
            and media.get("format") in {"TV", "TV_SHORT", "ONA", "OVA", "SPECIAL"}
        )

    async def search(self, query: str) -> list[dict]:
        if not query.strip():
            return []
        data = await self._request(SEARCH_QUERY, {"search": query, "perPage": MAX_RESULTS})
        page = data.get("Page") or {}
        items = page.get("media", []) if isinstance(page, dict) else []
        if not isinstance(items, list):
            raise AniListError("AniList 搜索结果格式无效")
        return [item for item in items[:MAX_RESULTS] if self.is_safe_anime(item)]

    async def get_media(self, media_id: int) -> dict | None:
        if media_id <= 0:
            return None
        media = (await self._request(DETAIL_QUERY, {"id": media_id})).get("Media")
        return media if self.is_safe_anime(media) else None

    @staticmethod
    def parse_date(value: dict | None) -> date | None:
        if not isinstance(value, dict):
            return None
        try:
            # 缺月、日时不猜测 1 月 1 日，防止写入虚假的首播日期。
            return date(value["year"], value["month"], value["day"])
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def titles(media: dict) -> list[str]:
        title = media.get("title") or {}
        return [
            value
            for value in [*title.values(), *(media.get("synonyms") or [])]
            if isinstance(value, str) and value.strip()
        ]

    @staticmethod
    def _text(description: str | None) -> str | None:
        if not description:
            return None
        return html.unescape(re.sub(r"<[^>]+>", "", description)).strip() or None

    def to_series(self, media: dict, language: str | None = None) -> TMDBSeries:
        title = media.get("title") or {}
        # AniList 不提供中文翻译；中文用户优先原名，其次罗马音，避免假翻译。
        preferred = title.get("english") if (language or "").startswith("en") else None
        name = preferred or title.get("native") or title.get("romaji") or str(media["id"])
        count = media.get("episodes")
        count = count if isinstance(count, int) and 0 < count <= MAX_EPISODES else None
        premiere = self.parse_date(media.get("startDate"))
        cover = media.get("coverImage") or {}
        poster = cover.get("extraLarge") or cover.get("large")
        overview = self._text(media.get("description"))
        season = TMDBSeason(
            season_number=1,
            name=name,
            overview=overview,
            air_date=premiere,
            poster_path=poster,
            episode_count=count,
        )
        score = media.get("averageScore")
        return TMDBSeries(
            id=-media["id"],
            metadata_source="anilist",
            anilist_id=media["id"],
            name=name,
            original_name=title.get("native") or title.get("romaji"),
            overview=overview,
            first_air_date=premiere,
            vote_average=score / 10 if isinstance(score, (int, float)) else None,
            poster_path=poster,
            backdrop_path=media.get("bannerImage"),
            genres=media.get("genres") or [],
            status={
                "FINISHED": "Ended",
                "RELEASING": "Returning Series",
                "NOT_YET_RELEASED": "Planned",
                "CANCELLED": "Canceled",
                "HIATUS": "In Production",
            }.get(media.get("status")),
            number_of_seasons=1,
            number_of_episodes=count,
            seasons=[season],
            adult=False,
        )

    def to_search_result(self, media: dict, language: str | None = None) -> TMDBSearchResult:
        series = self.to_series(media, language)
        fields = TMDBSearchResult.model_fields
        return TMDBSearchResult(**{k: v for k, v in series.model_dump().items() if k in fields})

    def to_season(self, media: dict, language: str | None = None) -> TMDBSeason:
        season = self.to_series(media, language).seasons[0]
        # AniList 没有单集标题和日期；仅为明确的总集数提供编号占位。
        season.episodes = [
            TMDBEpisode(episode_number=n, name=f"Episode {n}")
            for n in range(1, (season.episode_count or 0) + 1)
        ]
        return season
