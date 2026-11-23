"""The interactive API docs are off unless a developer turns them on (issue #47).

FastAPI serves /docs, /redoc and /openapi.json by default. /docs loads Swagger UI from a
third-party CDN, outside the page's Content-Security-Policy, and a public demo needs no API
console. Off is the default so that production needs no setting and a missing variable fails safe.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import API_DOCS_FLAG, api_docs_settings, app

DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
OFF = {"docs_url": None, "redoc_url": None, "openapi_url": None}


@pytest.mark.parametrize("path", DOC_PATHS)
def test_the_api_docs_are_not_served_by_default(path):
    app.state.answerer = None
    assert TestClient(app).get(path).status_code == 404


def test_unset_means_off(monkeypatch):
    monkeypatch.delenv(API_DOCS_FLAG, raising=False)
    assert api_docs_settings() == OFF


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "on", "2"])
def test_only_the_value_1_turns_them_on(monkeypatch, value):
    # One exact value, so a typo or a "false" that reads as truthy cannot open them by accident.
    monkeypatch.setenv(API_DOCS_FLAG, value)
    assert api_docs_settings() == OFF


def test_the_flag_turns_them_on_for_local_development(monkeypatch):
    monkeypatch.setenv(API_DOCS_FLAG, "1")
    local = FastAPI(**api_docs_settings())
    client = TestClient(local)
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path


def test_the_other_routes_still_work():
    app.state.answerer = None
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/saved").status_code == 200
