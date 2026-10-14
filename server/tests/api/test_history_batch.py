"""批量历史路由保留认证、请求约束与明确静态协议。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.deps import require_auth
from server.api.v1.history import get_history_batch_actions, router
from server.models.history_batch import HistoryBatchPreview, HistoryBatchResponse


@pytest.fixture
def batch_client():
    app = FastAPI()
    app.include_router(router)
    actions = SimpleNamespace(
        preview=AsyncMock(return_value=HistoryBatchPreview(groups=[], ungrouped_ids=[])),
        retry=AsyncMock(
            return_value=HistoryBatchResponse(results=[], success_count=0, failed_count=0)
        ),
        resolve=AsyncMock(
            return_value=HistoryBatchResponse(results=[], success_count=0, failed_count=0)
        ),
    )
    app.dependency_overrides[get_history_batch_actions] = lambda: actions
    with TestClient(app) as client:
        yield client, app, actions


@pytest.mark.parametrize("path", ["preview", "resolve", "retry"])
def test_batch_requires_auth(batch_client, path):
    client, _, actions = batch_client
    response = client.post(f"/api/history/batch/{path}", json={"record_ids": ["a"]})
    assert response.status_code == 401
    actions.preview.assert_not_awaited()
    actions.retry.assert_not_awaited()
    actions.resolve.assert_not_awaited()


@pytest.mark.parametrize("path", ["preview", "resolve", "retry"])
def test_batch_static_routes_accept_and_deduplicate(batch_client, path):
    client, app, actions = batch_client
    app.dependency_overrides[require_auth] = lambda: None
    body = {"record_ids": ["a", "a", "b"]}
    if path == "resolve":
        body.update(group_key="verified-key", tmdb_id=-123)
    response = client.post(f"/api/history/batch/{path}", json=body)
    assert response.status_code == 200
    method = getattr(actions, path)
    argument = method.await_args.args[0]
    assert (argument.record_ids if path == "resolve" else argument) == ["a", "b"]


@pytest.mark.parametrize("ids", [[], ["a"] * 101, [" "]])
@pytest.mark.parametrize("path", ["preview", "retry", "resolve"])
def test_batch_rejects_invalid_input(batch_client, ids, path):
    client, app, _ = batch_client
    app.dependency_overrides[require_auth] = lambda: None
    body = {"record_ids": ids}
    if path == "resolve":
        body.update(group_key="key", tmdb_id=123)
    assert client.post(f"/api/history/batch/{path}", json=body).status_code == 422
