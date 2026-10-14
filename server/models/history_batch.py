"""待处理记录批量操作协议；所有选择都由服务端重新验证。"""

from pydantic import BaseModel, Field, field_validator

from server.models.history import TaskStatus
from server.models.tmdb import TMDBSearchResult


class HistoryBatchRequest(BaseModel):
    record_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("record_ids")
    @classmethod
    def normalize_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 128 for value in values):
            raise ValueError("记录 ID 无效")
        return list(dict.fromkeys(values))


class HistoryBatchGroup(BaseModel):
    group_key: str
    folder_name: str
    record_ids: list[str]
    candidates: list[TMDBSearchResult]


class HistoryBatchPreview(BaseModel):
    groups: list[HistoryBatchGroup]
    ungrouped_ids: list[str]


class HistoryBatchResolveRequest(HistoryBatchRequest):
    group_key: str = Field(min_length=1, max_length=64)
    tmdb_id: int
    season: int | None = Field(default=None, ge=0, le=10000)


class HistoryBatchResult(BaseModel):
    record_id: str
    success: bool
    status: TaskStatus | None = None
    message: str


class HistoryBatchResponse(BaseModel):
    results: list[HistoryBatchResult]
    success_count: int
    failed_count: int
