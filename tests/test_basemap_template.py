from html.parser import HTMLParser
from pathlib import Path
import unittest

from flask import Flask, render_template

from routes.map import _fallback_context


class StatusParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.status_elements = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id") in {"map-status-banner", "map-status"}:
            self.status_elements[attributes["id"]] = attributes


class BasemapTemplateTests(unittest.TestCase):
    def test_missing_mapbox_token_never_renders_a_visible_status(self):
        root = Path(__file__).resolve().parents[1]
        app = Flask(__name__, template_folder=str(root / "templates"))
        context = _fallback_context()
        context.update(server_error=False, style_token_mismatch=True)
        with app.test_request_context():
            html = render_template("map.html", **context)
        parser = StatusParser()
        parser.feed(html)
        self.assertEqual(len(parser.status_elements), 2)
        for attributes in parser.status_elements.values():
            self.assertIn("hidden", attributes)
        self.assertNotIn("Mapbox-Stil benötigt Token", html)
        self.assertNotIn("Karte initialisiert", html)


if __name__ == "__main__":
    unittest.main()
