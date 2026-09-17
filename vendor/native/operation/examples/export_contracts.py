"""Regenerate JSON Schema and DEMO outputs from the installed/current source."""
from copy import deepcopy
import json
from pathlib import Path
from lastplate_operation import generate_operation_plan
from lastplate_operation.schemas.operation_input import OperationInput
from lastplate_operation.schemas.operation_output import OperationOutput
from lastplate_operation.tools.json_input import load_operation_json


def main():
    root=Path(__file__).resolve().parents[1]
    def write(path, data):
        (root/path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    for name,model in (("operation_input",OperationInput),("operation_output",OperationOutput)):
        write("contracts/"+name+".schema.json",model.model_json_schema())
    payload=load_operation_json((root/"examples/demo_input.json").read_text(encoding="utf-8"))
    write("examples/demo_output.json",generate_operation_plan(**payload))
    for name,policy in (("purchase_only","purchase_only"),("cooking_and_purchase","cooking_and_purchase")):
        case=deepcopy(payload)
        case["inventory_data"][0]["stock"]=66.0632
        case["config"].update(rounding_policy=policy,purchase_quantum={"g":100,"ml":1,"ea":1})
        if policy=="cooking_and_purchase":
            case["config"]["cooking_quantum"]={"g":100,"ml":1,"ea":1}
        # Serialize through the input model to retain numeric JSON representation.
        write("examples/"+name+"_input.json",OperationInput.model_validate(case).model_dump(mode="json"))
        write("examples/"+name+"_output.json",generate_operation_plan(**case))


if __name__=="__main__":
    main()
