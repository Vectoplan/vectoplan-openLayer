from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from routes.map import bp


def client():
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / "templates"), static_folder=str(root / "static"))
    app.register_blueprint(bp)
    return app.test_client()


def test_map_proxy_forwards_only_public_bytes_and_allowed_response_headers(monkeypatch):
    monkeypatch.setenv("VECTOPLAN_CORE_INTERNAL_API_KEY", "internal-test-key")
    upstream = SimpleNamespace(content=b"tile", status_code=200, headers={"Content-Type": "application/octet-stream",
        "X-Map-Storage": "project-database", "ETag": '"tile-sha"', "X-Private-Header": "private"})
    with patch("routes.map.requests.get", return_value=upstream) as request:
        response = client().get("/api/map/projects/core_test/tiles/openmaptiles/14/8801/5374")
    assert response.data == b"tile"
    assert response.headers["X-Map-Storage"] == "project-database"
    assert "X-Private-Header" not in response.headers
    assert request.call_args.kwargs["headers"]["X-Service-API-Key"] == "internal-test-key"
    assert request.call_args.kwargs["allow_redirects"] is False
    assert b"internal-test-key" not in response.data


def test_map_proxy_cannot_request_models_or_arbitrary_upstream_urls():
    with patch("routes.map.requests.get", side_effect=AssertionError("must not contact core")):
        for suffix in ("projects", "https://example.com/private", "tiles/../private", "style/mapbox"):
            assert client().get("/api/map/projects/core_test/" + suffix).status_code == 400


def test_terrain_renderer_carries_the_project_without_credentials():
    response = client().get("/map/terrain?map_project_id=core_test")
    assert b'"projectPublicId": "core_test"' in response.data
    assert b'"tokenUsable": false' in response.data
