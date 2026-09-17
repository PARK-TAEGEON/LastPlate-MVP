import json
from pathlib import Path
from lastplate_operation import generate_operation_plan
from lastplate_operation.tools.json_input import load_operation_json

if __name__ == "__main__":
    payload = load_operation_json(Path(__file__).with_name("demo_input.json").read_text(encoding="utf-8"))
    print(json.dumps(generate_operation_plan(**payload), ensure_ascii=False, indent=2))
