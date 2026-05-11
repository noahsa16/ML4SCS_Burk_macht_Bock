"""HTTP smokes that every dashboard static asset is served correctly.

ES modules fail silently in browsers when a 404 is served as text/html —
this test exists to make those failures loud during CI.
"""
from fastapi.testclient import TestClient
import pytest

from server import app

client = TestClient(app)


def test_root_serves_dashboard_shell():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "id=\"content\"" in r.text


def test_bootstrap_module_served_as_js():
    r = client.get("/static/dashboard.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]


@pytest.mark.parametrize(
    "path",
    [
        # Filled in as modules/views/stylesheets are created. Keep alphabetised.
        "/static/css/connections.css",
        "/static/css/sessions.css",
        "/static/css/system.css",
        "/static/js/core/anim.js",
        "/static/js/core/api.js",
        "/static/js/core/dom.js",
        "/static/js/core/format.js",
        "/static/js/core/router.js",
        "/static/js/core/state.js",
        "/static/js/core/status_cluster.js",
        "/static/js/core/theme.js",
        "/static/js/core/toast.js",
        "/static/js/core/ws.js",
        "/static/js/pages/connections.js",
        "/static/js/pages/sessions.js",
        "/static/js/pages/system.js",
        "/static/views/connections.html",
        "/static/views/sessions.html",
        "/static/views/system.html",
    ],
)
def test_static_assets_served(path):
    r = client.get(path)
    assert r.status_code == 200
    if path.endswith(".js"):
        assert "javascript" in r.headers["content-type"]
    elif path.endswith(".css"):
        assert "css" in r.headers["content-type"]
    elif path.endswith(".html"):
        assert "html" in r.headers["content-type"]
