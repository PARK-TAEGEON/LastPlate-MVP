"""Run from this project: python examples/inventory_v023_smoke.py /path/to/inventory-project"""
import json
import sys
from copy import deepcopy
from pathlib import Path
from lastplate_operation import generate_operation_plan
from lastplate_operation.integration import to_inventory_forecast


def main(root):
    sys.path.insert(0, str(Path(root).resolve()))
    from adapters.bundle import AdapterBundle
    from examples.forecast_wrapper import analyze_with_forecast
    bundle = AdapterBundle.demo()
    before = deepcopy(bundle.inventory.menus)
    payload = json.loads(Path(__file__).with_name("demo_input.json").read_text(encoding="utf-8"))
    report = generate_operation_plan(**payload)
    keys = sorted({(m.date.isoformat(), m.meal_type) for m in bundle.inventory.menus})
    # Synthetic count-only compatibility test, not a shared-stock weekly plan.
    meals = [dict(date=d, meal_type=m, operation_report=report) for d, m in keys]
    forecast = to_inventory_forecast(meals, forecast_version="operation-0.2.0", input_snapshot_id="DEMO-bridge-test")
    risk = analyze_with_forecast(bundle, {"as_of":"2026-09-17"}, forecast)
    assert risk["status"] == "ok", risk
    assert bundle.inventory.menus == before
    assert risk["forecast_version"] == "operation-0.2.0"
    assert all(r["expected_max_diners"] == 523 for r in forecast["rows"])
    print(json.dumps({"status":"PASS", "scope":"count-only v0.2.3 bridge", "meal_count":len(keys),
                      "recommended_servings":523, "original_menu_unchanged":True}))


if __name__ == "__main__":
    main(sys.argv[1])
