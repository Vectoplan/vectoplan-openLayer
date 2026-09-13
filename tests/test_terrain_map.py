import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from routes import map as map_routes


class TerrainMapTests(unittest.TestCase):
    def test_renderer_disables_all_mapbox_tokens(self):
        root = Path(__file__).resolve().parents[1]
        app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
        app.register_blueprint(map_routes.bp)
        for token, usable in [('pk.valid-public-browser-token', True), ('sk.private-token', False), ('', False)]:
            settings = SimpleNamespace(mapbox_token=token, map_default_style='mapbox/light-v11', map_tile_size=512)
            with patch.object(map_routes, '_settings', return_value=settings), patch.object(map_routes, '_build_context', side_effect=AssertionError('must not load project data')):
                response = app.test_client().get('/map/terrain')
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            config = json.loads(re.search(r'window.TERRAIN_BASEMAP_CONFIG = (.*);', html).group(1))
            self.assertFalse(config['tokenUsable'])
            self.assertEqual(config['token'], '')
            self.assertIn('js/basemap.js', html)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertNotIn('sk.private-token', html)
