"""CORS preflight for the Tauri webviews.

Windows' WebView2 is Chromium and runs the Private Network Access preflight for
`http://127.0.0.1`. Answering it without `Access-Control-Allow-Private-Network`
(Starlette answers 400 instead) turns every request into "Failed to fetch", and
only on Windows — WKWebView has no PNA. These tests pin both halves.
"""

import pytest
from fastapi.testclient import TestClient

from butter.api.app import create_app


@pytest.fixture()
def client():
    return TestClient(create_app())


def _preflight(client, origin, private_network=False):
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    if private_network:
        headers["Access-Control-Request-Private-Network"] = "true"
    return client.options("/api/accounts", headers=headers)


@pytest.mark.parametrize("origin", ["http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"])
def test_private_network_preflight_is_allowed(client, origin):
    res = _preflight(client, origin, private_network=True)
    assert res.status_code == 200, res.text
    assert res.headers["access-control-allow-private-network"] == "true"
    assert res.headers["access-control-allow-origin"] == origin


def test_preflight_without_pna_still_works(client):
    res = _preflight(client, "http://tauri.localhost")
    assert res.status_code == 200
    assert "access-control-allow-private-network" not in res.headers


def test_unknown_origin_is_rejected(client):
    res = _preflight(client, "https://evil.test", private_network=True)
    assert res.status_code == 400
    assert "origin" in res.text
