from __future__ import annotations

import os
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lastplate_backend.core.config import get_settings
from lastplate_backend.main import create_app


class ApiTests(unittest.TestCase):
    def test_create_get_and_recalculate_operation_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = os.path.join(directory, "lastplate-test.db")
            with patch.dict(os.environ, {"LASTPLATE_BACKEND_DATABASE_PATH": db_path}, clear=False):
                get_settings.cache_clear()
                with TestClient(create_app()) as client:
                    health = client.get("/api/v1/health")
                    self.assertEqual(health.status_code, 200)
                    self.assertEqual(health.json()["status"], "ok")

                    example_path = Path(__file__).resolve().parents[1] / "docs" / "examples" / "operation-plan-request.json"
                    example = client.post("/api/v1/operation-plans", json=json.loads(example_path.read_text(encoding="utf-8")))
                    self.assertEqual(example.status_code, 201, example.text)
                    self.assertGreater(example.json()["result"]["target"], 0)

                    mismatched_forecast = json.loads(example_path.read_text(encoding="utf-8"))
                    mismatched_forecast["forecast"]["site_id"] = "wrong-site"
                    invalid = client.post("/api/v1/operation-plans", json=mismatched_forecast)
                    self.assertEqual(invalid.status_code, 422)

                    create = client.post(
                        "/api/v1/operation-plans",
                        json={
                            "site_id": "demo-school",
                            "meal_date": "2026-09-18",
                            "meal_type": "lunch",
                            "current_time": "2026-09-18T09:00:00+09:00",
                            "forecast": {
                                "site_id": "demo-school",
                                "meal_date": "2026-09-18",
                                "meal_type": "lunch",
                                "lower": 80,
                                "mid": 90,
                                "upper": 100,
                                "model_version": "ml-0.1"
                            },
                            "menus": [
                                {
                                    "name": "카레",
                                    "recipe_g": {"감자": 100},
                                    "batches": [
                                        {
                                            "name": "1차 조리",
                                            "start": "2026-09-18T12:00:00+09:00",
                                            "planned": 90,
                                            "capacity": 150,
                                        }
                                    ],
                                }
                            ],
                            "inventory": [
                                {
                                    "ingredient": "감자",
                                    "available_kg": 10,
                                    "order_unit_kg": 1,
                                    "expires_on": "2026-09-19"
                                }
                            ],
                            "policy": {"demand_basis": "upper", "safety_buffer_people": 5},
                        },
                    )
                    self.assertEqual(create.status_code, 201, create.text)
                    plan = create.json()
                    self.assertEqual(plan["result"]["target"], 105)
                    self.assertEqual(plan["purchase_recommendations"][0]["recommended_order_kg"], 1.0)
                    self.assertEqual(plan["inventory_advisories"][0]["code"], "USE_FIRST_EXPIRING_STOCK")

                    fetched = client.get(f"/api/v1/operation-plans/{plan['id']}")
                    self.assertEqual(fetched.status_code, 200)
                    self.assertEqual(fetched.json()["id"], plan["id"])

                    latest = client.get(
                        "/api/v1/operation-plans/latest",
                        params={"site_id": "demo-school", "meal_date": "2026-09-18", "meal_type": "lunch"},
                    )
                    self.assertEqual(latest.status_code, 200)
                    self.assertEqual(latest.json()["id"], plan["id"])

                    capacity_limited = client.post(
                        "/api/v1/operation-plans",
                        json={
                            "site_id": "demo-school",
                            "meal_date": "2026-09-19",
                            "meal_type": "lunch",
                            "current_time": "2026-09-19T09:00:00+09:00",
                            "forecast": {
                                "site_id": "demo-school",
                                "meal_date": "2026-09-19",
                                "meal_type": "lunch",
                                "lower": 100,
                                "mid": 100,
                                "upper": 100,
                            },
                            "menus": [
                                {
                                    "name": "국",
                                    "recipe_g": {"물": 100},
                                    "batches": [
                                        {
                                            "name": "1차 조리",
                                            "start": "2026-09-19T12:00:00+09:00",
                                            "planned": 50,
                                            "capacity": 50,
                                        }
                                    ],
                                }
                            ],
                            "inventory": [{"ingredient": "물", "available_kg": 0, "order_unit_kg": 1}],
                        },
                    )
                    self.assertEqual(capacity_limited.status_code, 201, capacity_limited.text)
                    self.assertEqual(
                        capacity_limited.json()["purchase_recommendations"][0]["recommended_order_kg"], 5.0
                    )

                    updated = client.post(
                        f"/api/v1/operation-plans/{plan['id']}/events",
                        json={
                            "current_time": "2026-09-18T09:10:00+09:00",
                            "event": {"id": "field-trip", "status": "confirmed", "delta": 20},
                        },
                    )
                    self.assertEqual(updated.status_code, 201, updated.text)
                    revised = updated.json()
                    self.assertEqual(revised["parent_plan_id"], plan["id"])
                    self.assertEqual(revised["result"]["target"], 125)

                    latest_after_event = client.get(
                        "/api/v1/operation-plans/latest",
                        params={"site_id": "demo-school", "meal_date": "2026-09-18", "meal_type": "lunch"},
                    )
                    self.assertEqual(latest_after_event.status_code, 200)
                    self.assertEqual(latest_after_event.json()["id"], revised["id"])
                get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
