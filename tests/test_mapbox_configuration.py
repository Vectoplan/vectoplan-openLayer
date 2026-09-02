from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from settings import get_settings


TOKEN_ENV_NAMES = (
    "VECTOPLAN_OPENLAYER_MAPBOX_ACCESS_TOKEN",
    "VECTOPLAN_OPENLAYER_MAPBOX_TOKEN",
    "VECTOPLAN_MAPBOX_TOKEN",
    "MAPBOX_ACCESS_TOKEN",
    "MAPBOX_TOKEN",
)

CENTER_ENV_NAMES = (
    "DEFAULT_LON",
    "DEFAULT_LAT",
    "MAP_DEFAULT_LON",
    "MAP_DEFAULT_LAT",
    "MAP_DEFAULT_CENTER",
)


def _settings_for(environment: dict[str, str]):
    clean_environment = {
        name: "" for name in (*TOKEN_ENV_NAMES, *CENTER_ENV_NAMES)
    }
    clean_environment.update(environment)
    with patch.dict("os.environ", clean_environment, clear=False):
        get_settings.cache_clear()
        settings = get_settings()
    get_settings.cache_clear()
    return settings


class MapboxConfigurationTests(unittest.TestCase):
    def test_openlayer_defaults_to_berlin_without_project_coordinates(self) -> None:
        settings = _settings_for({})

        self.assertEqual(settings.map_default_center, (13.405, 52.52))

    def test_all_browser_and_emergency_fallbacks_use_berlin(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "config.py",
            "settings.py",
            "routes/map.py",
            "templates/map.html",
            "static/js/main.js",
        ):
            with self.subTest(path=relative_path):
                source = (root / relative_path).read_text(encoding="utf-8")
                self.assertNotIn("11.576124", source)
                self.assertNotIn("48.137154", source)

    def test_openlayer_accepts_every_supported_mapbox_token_alias(self) -> None:
        for name in TOKEN_ENV_NAMES:
            with self.subTest(name=name):
                settings = _settings_for(
                    {name: "pk.alias-token-for-openlayer"},
                )
                self.assertEqual(
                    settings.mapbox_token,
                    "pk.alias-token-for-openlayer",
                )
                self.assertTrue(settings.has_mapbox_token)

    def test_openlayer_service_specific_token_wins(self) -> None:
        settings = _settings_for(
            {
                "MAPBOX_ACCESS_TOKEN": "pk.global-token",
                "VECTOPLAN_OPENLAYER_MAPBOX_ACCESS_TOKEN": "pk.service-token",
            }
        )

        self.assertEqual(settings.mapbox_token, "pk.service-token")
        flask_config = settings.to_flask_config()
        self.assertEqual(
            flask_config["MAPBOX_ACCESS_TOKEN"],
            "pk.service-token",
        )
        self.assertEqual(flask_config["MAPBOX_TOKEN"], "pk.service-token")
        self.assertEqual(
            flask_config["VECTOPLAN_MAPBOX_TOKEN"],
            "pk.service-token",
        )


if __name__ == "__main__":
    unittest.main()
