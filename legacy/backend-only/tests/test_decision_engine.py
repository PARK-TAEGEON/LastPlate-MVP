from __future__ import annotations

import unittest

from lastplate_backend.engine import DecisionValidationError, calculate_decision


NOW = "2026-09-18T09:00:00+09:00"


def menu(name: str, recipe_g: dict[str, int], batches: list[dict], **extra: object) -> dict:
    return {"name": name, "recipe_g": recipe_g, "batches": batches, **extra}


class DecisionEngineTests(unittest.TestCase):
    def test_confirmed_event_and_safety_buffer_change_target(self) -> None:
        result = calculate_decision(
            prediction={"lower": 100, "mid": 110, "upper": 120},
            events=[
                {"id": "field-trip", "status": "confirmed", "delta": 35},
                {"id": "tentative-visitor", "status": "pending", "delta": 10},
            ],
            menus=[
                menu(
                    "비빔밥",
                    {"쌀": 120},
                    [{"name": "1차", "start": "2026-09-18T12:00:00+09:00", "planned": 120, "capacity": 200}],
                )
            ],
            current_time=NOW,
            inventory_kg={"쌀": 30},
            policy={"demand_basis": "upper", "safety_buffer_people": 5, "safety_buffer_rate": 0},
        )

        self.assertEqual(result["event_delta"], 35)
        self.assertEqual(result["applied_event_ids"], ["field-trip"])
        self.assertEqual(result["target"], 160)
        self.assertEqual(result["menus"][0]["final"], 160)
        self.assertEqual(result["menus"][0]["future"][0]["change"], 40)

    def test_started_batch_is_locked_when_headcount_decreases(self) -> None:
        result = calculate_decision(
            prediction={"lower": 90, "mid": 100, "upper": 120},
            events=[{"id": "cancellation", "status": "confirmed", "delta": -20}],
            menus=[
                menu(
                    "국",
                    {"물": 100},
                    [
                        {
                            "name": "이미 시작",
                            "start": "2026-09-18T08:30:00+09:00",
                            "planned": 80,
                            "capacity": 80,
                            "status": "cooking",
                            "fixed_qty": 80,
                        },
                        {
                            "name": "2차",
                            "start": "2026-09-18T11:00:00+09:00",
                            "planned": 60,
                            "capacity": 80,
                        },
                    ],
                )
            ],
            current_time=NOW,
            inventory_kg={"물": 20},
        )

        plan = result["menus"][0]
        self.assertEqual(result["target"], 100)
        self.assertEqual(plan["locked"], 80)
        self.assertEqual(plan["future"][0]["qty"], 20)
        self.assertEqual(plan["final"], 100)

    def test_shared_inventory_is_not_double_counted(self) -> None:
        result = calculate_decision(
            prediction={"lower": 10, "mid": 10, "upper": 10},
            events=[],
            menus=[
                menu(
                    "두부조림",
                    {"두부": 100},
                    [{"name": "1차", "start": "2026-09-18T12:00:00+09:00", "planned": 10, "capacity": 10}],
                ),
                menu(
                    "두부국",
                    {"두부": 200},
                    [{"name": "1차", "start": "2026-09-18T12:05:00+09:00", "planned": 10, "capacity": 10}],
                ),
            ],
            current_time=NOW,
            inventory_kg={"두부": 2},
        )

        first, second = result["menus"]
        tofu = result["inventory"][0]
        self.assertEqual(first["final"], 10)
        self.assertEqual(second["final"], 5)
        self.assertEqual(second["shortage"], 5)
        self.assertAlmostEqual(tofu["needed_for_target_kg"], 3.0)
        self.assertAlmostEqual(tofu["additional_kg_for_target"], 1.0)
        self.assertIn("INVENTORY_SHORTAGE", result["warnings"])

    def test_minimum_and_nutrition_constraints_are_reported(self) -> None:
        result = calculate_decision(
            prediction={"lower": 10, "mid": 10, "upper": 10},
            events=[],
            menus=[
                menu(
                    "반찬",
                    {"채소": 100},
                    [{"name": "1차", "start": "2026-09-18T12:00:00+09:00", "planned": 10, "capacity": 20}],
                    minimum_servings=15,
                    nutrition_per_portion={"kcal": 100},
                )
            ],
            current_time=NOW,
            inventory_kg={"채소": 2},
            constraints={"minimum_nutrition_per_guest": {"kcal": 200}},
        )

        self.assertEqual(result["menus"][0]["target"], 15)
        self.assertEqual(result["menus"][0]["final"], 15)
        self.assertEqual(result["constraints"]["nutrition_per_guest"]["kcal"], 150)
        self.assertEqual(result["constraints"]["violations"][0]["code"], "NUTRITION_BELOW_MINIMUM")

    def test_conflicting_duplicate_event_is_rejected(self) -> None:
        with self.assertRaises(DecisionValidationError):
            calculate_decision(
                prediction={"lower": 1, "mid": 1, "upper": 1},
                events=[
                    {"id": "same", "status": "confirmed", "delta": 1},
                    {"id": "same", "status": "confirmed", "delta": 2},
                ],
                menus=[
                    menu(
                        "밥",
                        {"쌀": 100},
                        [{"name": "1차", "start": "2026-09-18T12:00:00+09:00", "planned": 1, "capacity": 1}],
                    )
                ],
                current_time=NOW,
                inventory_kg={"쌀": 1},
            )


if __name__ == "__main__":
    unittest.main()
