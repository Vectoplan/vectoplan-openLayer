from __future__ import annotations

import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from flask import Flask

from routes import datasets as dataset_routes
from src.datasets.source_service import (
    OpenLayerDatasetSourcePayloadTooLargeError,
    OpenLayerDatasetSourceService,
)
from src.exports.export_service import build_export_artifact, pdf_bbox_for_scale


SAMPLE_PAYLOAD = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[11.5769, 48.1370], [11.5771, 48.1372]],
            },
            "properties": {"name": "line"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [11.5770, 48.1371]},
            "properties": {"name": "point"},
        },
    ],
}


def source_service_stub() -> OpenLayerDatasetSourceService:
    service = object.__new__(OpenLayerDatasetSourceService)
    service.feature_limit = 1000
    return service


class ViewportSourceServiceTests(unittest.TestCase):
    def test_wfs_url_contains_bbox_and_hard_limit(self) -> None:
        service = source_service_stub()
        limited = service._apply_feature_limit_to_wfs_url(
            raw_url=(
                "https://geo.example/wfs?service=WFS&request=GetFeature"
                "&typeNames=workspace:roads&count=100&maxFeatures=100"
            ),
            feature_limit=5000,
        )
        bounded = service._apply_bbox_to_wfs_url(
            raw_url=limited,
            bbox=(11.5, 48.1, 11.6, 48.2),
            bbox_crs="CRS:84",
        )
        query = parse_qs(urlsplit(bounded).query)
        self.assertEqual(query["count"], ["1000"])
        self.assertEqual(query["maxFeatures"], ["1000"])
        self.assertEqual(query["bbox"], ["11.5,48.1,11.6,48.2,CRS:84"])
        self.assertEqual(query["srsName"], ["CRS:84"])

    def test_oversized_wfs_response_retries_with_smaller_feature_limit(self) -> None:
        service = source_service_stub()
        service._fetch_json_source = Mock(
            side_effect=[
                OpenLayerDatasetSourcePayloadTooLargeError(
                    "payload too large",
                    details={"max_payload_bytes": 12 * 1024 * 1024},
                ),
                {
                    "status_code": 200,
                    "headers": {},
                    "payload": {"type": "FeatureCollection", "features": []},
                    "notes": [],
                },
            ]
        )

        result = service._fetch_json_source_with_wfs_backoff(
            dataset_id="flood",
            effective_url=(
                "https://geo.example/wfs?service=WFS&request=GetFeature"
                "&typeNames=workspace:flood&count=1000&maxFeatures=1000"
            ),
            source_type="wfs",
            feature_limit=1000,
        )

        self.assertEqual(result["effective_feature_limit"], 500)
        retry_url = service._fetch_json_source.call_args_list[1].kwargs["effective_url"]
        retry_query = parse_qs(urlsplit(retry_url).query)
        self.assertEqual(retry_query["count"], ["500"])
        self.assertEqual(retry_query["maxFeatures"], ["500"])
        self.assertIn("wfs_payload_backoff_applied:1000->500", result["notes"])

    def test_geojson_is_filtered_before_limit(self) -> None:
        service = source_service_stub()
        payload = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [20, 20]}},
            ],
        }
        normalized, meta = service._normalize_geojson_payload(
            dataset_id="points",
            payload=payload,
            feature_limit=1000,
            bbox=(0, 0, 2, 2),
        )
        self.assertEqual(len(normalized["features"]), 1)
        self.assertEqual(meta["feature_count_after_trim"], 1)
        self.assertIn("feature_collection_filtered_by_bbox", meta["notes"])


    def test_geojson_is_filtered_to_400_meter_circle(self) -> None:
        service = source_service_stub()
        payload = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.002, 0.0]}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.003, 0.003]}},
            ],
        }
        normalized, meta = service._normalize_geojson_payload(
            dataset_id="points",
            payload=payload,
            feature_limit=1000,
            bbox=(-0.004, -0.004, 0.004, 0.004),
            circle_center=(0.0, 0.0),
            circle_radius_m=400,
        )
        self.assertEqual(len(normalized["features"]), 1)
        self.assertEqual(normalized["features"][0]["geometry"]["coordinates"], [0.002, 0.0])
        self.assertIn("feature_collection_filtered_by_circle", meta["notes"])


class ExportServiceTests(unittest.TestCase):
    def test_pdf_bbox_matches_a4_map_frame_scale(self) -> None:
        center = (11.576124, 48.137154)
        bbox_100 = pdf_bbox_for_scale(center, 100)
        bbox_1000 = pdf_bbox_for_scale(center, 1000)

        def dimensions_m(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
            width = (
                math.radians(bbox[2] - bbox[0])
                * 6_378_137.0
                * math.cos(math.radians(center[1]))
            )
            height = math.radians(bbox[3] - bbox[1]) * 6_378_137.0
            return width, height

        width_100, height_100 = dimensions_m(bbox_100)
        width_1000, height_1000 = dimensions_m(bbox_1000)
        self.assertAlmostEqual(width_100, 18.6, places=3)
        self.assertAlmostEqual(height_100, 25.3, places=3)
        self.assertAlmostEqual(width_1000, 186.0, places=3)
        self.assertAlmostEqual(height_1000, 253.0, places=3)

    def test_dxf_and_pdf_are_real_format_payloads(self) -> None:
        common = {
            "dataset_id": "roads",
            "dataset_title": "Roads",
            "payload": SAMPLE_PAYLOAD,
            "center": (11.5770, 48.1371),
        }
        dxf = build_export_artifact(export_format="dxf", **common)
        pdf = build_export_artifact(export_format="pdf", scale=100, **common)
        self.assertTrue(dxf.content.startswith(b"0\nSECTION\n"))
        self.assertIn(b"POLYLINE", dxf.content)
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.assertTrue(pdf.filename.endswith("_M100.pdf"))

    def test_invalid_pdf_scale_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "100 or 1000"):
            build_export_artifact(
                export_format="pdf",
                dataset_id="roads",
                dataset_title="Roads",
                payload=SAMPLE_PAYLOAD,
                center=(11.5770, 48.1371),
                scale=500,
            )


class DatasetRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.register_blueprint(dataset_routes.bp)
        self.client = self.app.test_client()
        self.settings = SimpleNamespace(
            dataset_api_enabled=True,
            dataset_export_enabled=True,
            dataset_min_load_zoom=14,
            dataset_feature_limit=1000,
            dataset_radius_meters=400,
            dwg_converter_command="dxf2dwg",
        )

    def test_public_catalog_limit_ignores_historic_100_value(self) -> None:
        with (
            self.app.test_request_context(),
            patch.object(dataset_routes, "_settings", return_value=self.settings),
        ):
            item = dataset_routes._normalize_public_dataset_item(
                {
                    "id": "roads",
                    "title": "Roads",
                    "source": {
                        "type": "wfs",
                        "available": True,
                        "max_features": 100,
                    },
                },
                include_internal=False,
            )
        self.assertEqual(item["source"]["max_features"], 1000)

    def test_source_does_not_call_upstream_below_minimum_zoom(self) -> None:
        source_service = Mock()
        with (
            patch.object(dataset_routes, "_settings", return_value=self.settings),
            patch.object(dataset_routes, "_get_dataset_source_service", return_value=source_service),
        ):
            response = self.client.get(
                "/api/datasets/roads/source?bbox=11.5,48.1,11.6,48.2&bbox_crs=CRS:84&zoom=13"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["features"], [])
        source_service.get_dataset_source.assert_not_called()

    def test_source_passes_viewport_and_1000_limit(self) -> None:
        source_service = Mock()
        source_service.get_dataset_source.return_value = SimpleNamespace(
            dataset_id="roads",
            provider="geoserver",
            feature_count=2,
            feature_limit=1000,
            trimmed=False,
            from_cache=False,
            stale_cache_used=False,
            payload=SAMPLE_PAYLOAD,
        )
        with (
            patch.object(dataset_routes, "_settings", return_value=self.settings),
            patch.object(dataset_routes, "_get_dataset_source_service", return_value=source_service),
        ):
            response = self.client.get(
                "/api/datasets/roads/source?bbox=11.5,48.1,11.6,48.2&lon=11.55&lat=48.15&radius_m=5000&zoom=14"
            )
        self.assertEqual(response.status_code, 200)
        expected_bbox = dataset_routes._bbox_for_location_radius((11.55, 48.15), 400)
        source_service.get_dataset_source.assert_called_once_with(
            "roads",
            use_cache=True,
            bbox=expected_bbox,
            bbox_crs="CRS:84",
            circle_center=(11.55, 48.15),
            circle_radius_m=400,
            feature_limit=1000,
        )

        self.assertEqual(response.headers["X-OpenLayer-Radius-Meters"], "400")

    def test_source_returns_progressive_feature_batches(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": f"feature-{index}",
                    "geometry": {"type": "Point", "coordinates": [11.55, 48.15]},
                    "properties": {"index": index},
                }
                for index in range(230)
            ],
        }
        source_service = Mock()
        source_service.get_dataset_source.return_value = SimpleNamespace(
            dataset_id="roads",
            provider="geoserver",
            feature_count=230,
            feature_limit=1000,
            trimmed=False,
            from_cache=True,
            stale_cache_used=False,
            payload=payload,
        )
        with (
            patch.object(dataset_routes, "_settings", return_value=self.settings),
            patch.object(dataset_routes, "_get_dataset_source_service", return_value=source_service),
        ):
            response = self.client.get(
                "/api/datasets/roads/source?lon=11.55&lat=48.15&zoom=14&offset=100&batch_size=100"
            )

        self.assertEqual(response.status_code, 200)
        page = response.get_json()
        self.assertEqual(len(page["features"]), 100)
        self.assertEqual(page["features"][0]["id"], "feature-100")
        self.assertEqual(page["features"][-1]["id"], "feature-199")
        self.assertEqual(response.headers["X-OpenLayer-Feature-Count"], "100")
        self.assertEqual(response.headers["X-OpenLayer-Total-Available"], "230")
        self.assertEqual(response.headers["X-OpenLayer-Has-More"], "true")
        self.assertEqual(response.headers["X-OpenLayer-Next-Offset"], "200")
    def test_bbox_is_required(self) -> None:
        with patch.object(dataset_routes, "_settings", return_value=self.settings):
            response = self.client.get("/api/datasets/roads/source?zoom=14")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
