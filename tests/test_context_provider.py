from types import SimpleNamespace
from flask import Flask
from routes import map as map_routes


def test_cad_design_provider_ignores_legacy_mapbox_tokens(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(map_routes.bp)
    settings = SimpleNamespace(mapbox_token="pk.browser-token", map_default_style="mapbox/light-v11")
    monkeypatch.setattr(map_routes, "_settings", lambda: settings)
    response = app.test_client().get("/api/map/context-provider")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["designProvider"] == "openfreemap"
    assert b"browser-token" not in response.data
    assert payload["fallback"]["id"] == "osm"
    settings.mapbox_token = "sk.secret-token"
    response = app.test_client().get("/api/map/context-provider")
    assert response.get_json()["provider"]["id"] == "osm"
    assert b"secret-token" not in response.data
