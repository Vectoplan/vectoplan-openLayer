from __future__ import annotations

import unittest
from pathlib import Path

from src.styles.style_adapter import OpenLayerStyleAdapter


class AttributeRuleAdapterTests(unittest.TestCase):
    def test_condition_label_and_default_style_reach_openlayer_contract(self) -> None:
        adapter = object.__new__(OpenLayerStyleAdapter)
        contract = adapter._adapt_style_payload(
            dataset_id="hochwasser",
            raw_style_payload={
                "geometry": "polygon",
                "default": {
                    "fill": "#112233",
                    "fill_opacity": 0.4,
                    "stroke": "#445566",
                    "label_enabled": True,
                    "label_field": "flurnummer",
                    "label_size": 14,
                    "label_color": "#17212B",
                    "label_halo_color": "#FFFFFF",
                    "label_halo_width": 2,
                    "label_placement": "point",
                    "label_priority": 9,
                },
                "rules": [
                    {
                        "id": "geringes-risiko",
                        "label": "Geringes Risiko",
                        "when": {
                            "field": "vecto_Überflutungsfläche",
                            "eq": "Geringes Risiko",
                        },
                        "style": {
                            "fill": "#F2C94C",
                            "fill_opacity": 0.7,
                            "stroke": "#8A6D00",
                            "z_index": 10,
                        },
                    }
                ],
            },
            dataset_entry=None,
            style_url=None,
            style_path=None,
            geometry_type="Polygon",
            include_rules=True,
            include_raw_style=False,
            source="test",
            valid=True,
        )

        payload = contract.to_dict()
        self.assertEqual(payload["default_style"]["fill_color"], "rgba(17,34,51,0.400)")
        self.assertEqual(payload["label"]["field"], "flurnummer")
        self.assertEqual(payload["label"]["placement"], "point")
        self.assertEqual(payload["label"]["priority"], 9)
        self.assertEqual(payload["rules"][0]["filter"]["field"], "vecto_Überflutungsfläche")
        self.assertEqual(payload["rules"][0]["filter"]["eq"], "Geringes Risiko")
        self.assertFalse(payload["rules"][0]["else"])
        self.assertEqual(payload["rules"][0]["style"]["fill_color"], "rgba(242,201,76,0.700)")
        self.assertEqual(payload["rules"][0]["style"]["z_index"], 10)

    def test_rule_priority_is_applied_independently_from_label_priority(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "static" / "js" / "main.js").read_text(encoding="utf-8")
        self.assertIn("zIndex: options.zIndex", script)
        self.assertIn("100 + clamp(numOr(labelOptions.priority, 5), 1, 10)", script)
        self.assertIn("return [baseStyle, labelStyle]", script)

if __name__ == "__main__":
    unittest.main()