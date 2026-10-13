"""Unit tests for TMDB API endpoints.

测试 /api/tmdb 路由的各项功能。
使用 conftest.py 中的 auth_client fixture 绕过认证。
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from server.bootstrap import get_tmdb_service
from server.common.exceptions import TMDBConnectionError, TMDBTimeoutError
from server.domain.metadata.tmdb_service import TMDBService
from server.domain.system.config_service import ConfigService
from server.main import app
from server.models.tmdb import (
    TMDBEpisode,
    TMDBSearchResponse,
    TMDBSearchResult,
    TMDBSeason,
    TMDBSeries,
)


@pytest.fixture
def tmdb_client(temp_db: Path, override_auth) -> TestClient:
    """
    提供带有 TMDB 服务和认证覆盖的测试客户端。

    Args:
        temp_db: Temporary database path.
        override_auth: Authentication override fixture.

    Returns:
        Configured test client.
    """
    config_service = ConfigService(db_path=temp_db)
    tmdb_service = TMDBService(config_service=config_service)

    def override_tmdb_service():
        return tmdb_service

    app.dependency_overrides[get_tmdb_service] = override_tmdb_service
    # 默认模拟季/集基础调用，整个 API 单元测试禁止外部网络。
    with patch.object(TMDBService, "get_series_by_api", new_callable=AsyncMock) as series_mock, \
         patch.object(TMDBService, "get_season_by_api", new_callable=AsyncMock) as season_mock:
        series_mock.return_value = TMDBSeries(id=1396, name="R18 Test Series", adult=True)
        season_mock.return_value = None
        yield TestClient(app)
    # 清理所有覆盖
    app.dependency_overrides.clear()


class TestTMDBSearchAPI:
    """Tests for /api/tmdb/search endpoint."""

    def test_search_empty_query(self, tmdb_client):
        """Test search with empty query returns 422."""
        response = tmdb_client.get("/api/tmdb/search?q=")
        assert response.status_code == 422

    def test_search_missing_query(self, tmdb_client):
        """Test search without query parameter returns 422."""
        response = tmdb_client.get("/api/tmdb/search")
        assert response.status_code == 422

    def test_search_mocked_success(self, tmdb_client):
        """Test search with mocked successful response."""
        mock_response = TMDBSearchResponse(
            query="Breaking Bad",
            total_results=1,
            results=[
                TMDBSearchResult(
                    id=1396,
                    adult=True,
                    name="Breaking Bad",
                    original_name="Breaking Bad",
                    vote_average=8.9,
                )
            ],
        )

        with patch.object(
            TMDBService, "search_series_by_api", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = mock_response

            response = tmdb_client.get("/api/tmdb/search?q=Breaking+Bad&r18=true")

            assert response.status_code == 200
            data = response.json()
            assert data["query"] == "Breaking Bad"
            assert data["total_results"] == 1
            assert len(data["results"]) == 1
            assert data["results"][0]["id"] == 1396

    def test_search_mocked_timeout(self, tmdb_client):
        """Test search with timeout error returns 408."""
        with patch.object(
            TMDBService, "search_series_by_api", new_callable=AsyncMock
        ) as mock_search:
            mock_search.side_effect = TMDBTimeoutError("/search/tv")

            response = tmdb_client.get("/api/tmdb/search?q=test&r18=true")

            assert response.status_code == 408
            data = response.json()
            assert "error" in data
            assert "超时" in data["error"]["message"]

    def test_search_mocked_connection_error(self, tmdb_client):
        """Test search with connection error returns 502."""
        with patch.object(
            TMDBService, "search_series_by_api", new_callable=AsyncMock
        ) as mock_search:
            mock_search.side_effect = TMDBConnectionError("connection failed")

            response = tmdb_client.get("/api/tmdb/search?q=test&r18=true")

            assert response.status_code == 502
            data = response.json()
            assert "error" in data
            assert "连接失败" in data["error"]["message"]

    def test_search_with_language_parameter(self, tmdb_client):
        """Test search with custom language parameter."""
        mock_response = TMDBSearchResponse(
            query="test",
            total_results=0,
            results=[],
        )

        with patch.object(
            TMDBService, "search_series_by_api", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = mock_response

            response = tmdb_client.get("/api/tmdb/search?q=test&language=en-US&r18=true")

            assert response.status_code == 200
            mock_search.assert_called_once_with("test", "en-US", include_adult=True)


class TestTMDBSeriesAPI:
    """Tests for /api/tmdb/series/{tmdb_id} endpoint."""

    def test_get_series_mocked_success(self, tmdb_client):
        """Test getting series with mocked response."""
        mock_series = TMDBSeries(
            id=1396,
            adult=True,
            name="Breaking Bad",
            original_name="Breaking Bad",
            overview="A high school chemistry teacher...",
            vote_average=8.9,
            genres=["Drama", "Crime"],
            status="Ended",
            number_of_seasons=5,
            seasons=[
                TMDBSeason(season_number=1, name="Season 1"),
                TMDBSeason(season_number=2, name="Season 2"),
            ],
        )

        with patch.object(
            TMDBService, "get_series_by_api", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_series

            response = tmdb_client.get("/api/tmdb/series/1396?r18=true")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 1396
            assert data["name"] == "Breaking Bad"
            assert len(data["seasons"]) == 2

    def test_get_series_not_found(self, tmdb_client):
        """Test getting non-existent series returns 404."""
        with patch.object(
            TMDBService, "get_series_by_api", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None

            response = tmdb_client.get("/api/tmdb/series/99999999?r18=true")

            assert response.status_code == 404
            data = response.json()
            assert "error" in data
            assert "未找到" in data["error"]["message"]

    def test_get_series_timeout(self, tmdb_client):
        """Test getting series with timeout returns 408."""
        with patch.object(
            TMDBService, "get_series_by_api", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = TMDBTimeoutError("/tv/1396")

            response = tmdb_client.get("/api/tmdb/series/1396?r18=true")

            assert response.status_code == 408

    def test_get_series_without_episodes(self, tmdb_client):
        """Test getting series without episode details."""
        mock_series = TMDBSeries(
            id=1396,
            adult=True,
            name="Breaking Bad",
        )

        with patch.object(
            TMDBService, "get_series_by_api", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_series

            response = tmdb_client.get("/api/tmdb/series/1396?include_episodes=false&r18=true")

            assert response.status_code == 200
            mock_get.assert_called_once_with(
                1396, "zh-CN"
            )


class TestTMDBSeasonAPI:
    """Tests for /api/tmdb/series/{tmdb_id}/season/{season_number} endpoint."""

    def test_get_season_mocked_success(self, tmdb_client):
        """Test getting season with mocked response."""
        mock_season = TMDBSeason(
            season_number=1,
            name="Season 1",
            overview="The first season...",
            episode_count=7,
            episodes=[
                TMDBEpisode(episode_number=1, name="Pilot"),
                TMDBEpisode(episode_number=2, name="Cat's in the Bag..."),
            ],
        )

        with patch.object(
            TMDBService, "get_season_by_api", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_season

            response = tmdb_client.get("/api/tmdb/series/1396/season/1?r18=true")

            assert response.status_code == 200
            data = response.json()
            assert data["season_number"] == 1
            assert data["episode_count"] == 7
            assert len(data["episodes"]) == 2

    def test_get_season_not_found(self, tmdb_client):
        """Test getting non-existent season returns 404."""
        with patch.object(
            TMDBService, "get_season_by_api", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None

            response = tmdb_client.get("/api/tmdb/series/1396/season/99?r18=true")

            assert response.status_code == 404

    def test_get_season_with_language(self, tmdb_client):
        """Test getting season with custom language."""
        mock_season = TMDBSeason(season_number=1, name="第一季")

        with patch.object(
            TMDBService, "get_season_by_api", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_season

            response = tmdb_client.get("/api/tmdb/series/1396/season/1?language=zh-CN&r18=true")

            assert response.status_code == 200
            mock_get.assert_called_once_with(
                1396, 1, "zh-CN"
            )

    def test_get_season_invalid_season_number(self, tmdb_client):
        """Test getting season with invalid season number."""
        response = tmdb_client.get("/api/tmdb/series/1396/season/abc")
        assert response.status_code == 422


class TestAnimeMetadataAPI:
    """默认表番接口通过双源聚合，负 ID 保留 AniList 来源。"""

    def test_default_search_uses_anime_provider(self, tmdb_client):
        from server.domain.metadata.anime_metadata_service import AnimeMetadataService

        search_response = TMDBSearchResponse(query="Anime", total_results=1, results=[
            TMDBSearchResult(id=-7, name="Anime", metadata_source="anilist", anilist_id=7)
        ])
        with patch.object(AnimeMetadataService, "search_series_by_api", new_callable=AsyncMock) as search:
            search.return_value = search_response
            response = tmdb_client.get("/api/tmdb/search?q=Anime")
        assert response.status_code == 200
        assert response.json()["results"][0]["metadata_source"] == "anilist"
        search.assert_awaited_once_with("Anime", "zh-CN")

    def test_anilist_series_and_season(self, tmdb_client):
        from server.domain.metadata.anime_metadata_service import AnimeMetadataService

        season = TMDBSeason(season_number=1, name="Season 1", episodes=[
            TMDBEpisode(episode_number=1, name="Episode 1")
        ])
        series = TMDBSeries(id=-7, name="Anime", metadata_source="anilist",
                            anilist_id=7, seasons=[season])
        with patch.object(AnimeMetadataService, "get_series_by_api", new_callable=AsyncMock) as details, \
             patch.object(AnimeMetadataService, "get_season_by_api", new_callable=AsyncMock) as seasons:
            details.return_value = series
            seasons.return_value = season
            response = tmdb_client.get("/api/tmdb/series/-7")
            assert response.status_code == 200
            assert response.json()["anilist_id"] == 7
            response = tmdb_client.get("/api/tmdb/series/-7/season/1")
            assert response.status_code == 200
            assert response.json()["episodes"][0]["episode_number"] == 1

    def test_r18_rejects_anilist_id(self, tmdb_client):
        assert tmdb_client.get("/api/tmdb/series/-7?r18=true").status_code == 404
        assert tmdb_client.get("/api/tmdb/series/-7/season/1?r18=true").status_code == 404

    def test_adult_id_cannot_bypass_anime_mode(self, tmdb_client):
        from server.domain.metadata.anime_metadata_service import AnimeMetadataService

        with patch.object(AnimeMetadataService, "get_series_by_api", new_callable=AsyncMock) as details:
            details.return_value = TMDBSeries(id=1396, name="Adult", adult=True)
            assert tmdb_client.get("/api/tmdb/series/1396").status_code == 404
            assert tmdb_client.get("/api/tmdb/series/1396/season/1").status_code == 404
