from typing import Protocol
from schemas.models import InventoryLot, Menu, IngredientAmount
from .local import DEMO_DIR, excel_rows, validate_row, fail

class InventoryAdapter(Protocol):
    source: str
    menu_source: str
    def get_inventory(self) -> list[InventoryLot]: ...
    def get_weekly_menu(self) -> list[Menu]: ...

class DemoInventoryAdapter:
    source = "DEMO:food_inventory.xlsx"
    menu_source = "DEMO:weekly_menu.xlsx"
    def __init__(self, directory=DEMO_DIR):
        from pathlib import Path
        directory = Path(directory)
        required=[k for k,v in InventoryLot.model_fields.items() if v.is_required()]
        self.inventory = [validate_row(InventoryLot,r,{k:v for k,v in r.items() if k != "source_type"}) for r in excel_rows(directory / "food_inventory.xlsx",required)]
        grouped = {}
        seen={}
        duplicates=[]
        self.validation_warnings=[]
        for r in excel_rows(directory / "weekly_menu.xlsx",("date","meal_type","menu_name","ingredient","serving_amount","unit","expected_max_diners")):
            if r.get("target_group") not in (None,""):
                fail(r,"target_group","Current Menu schema has no target_group; group rows cannot be merged safely")
            amount=validate_row(IngredientAmount,r,dict(ingredient=r["ingredient"],amount_per_serving=r["serving_amount"],unit=r["unit"]))
            checked=validate_row(Menu,r,dict(date=r["date"],meal_type=r["meal_type"],menu_name=r["menu_name"],expected_max_diners=r["expected_max_diners"],ingredients=[amount]))
            # Each row is one ingredient contribution, not one whole menu.
            row_key=(checked.date,checked.meal_type,checked.menu_name,amount.ingredient)
            fingerprint={**r,"date":checked.date,"serving_amount":amount.amount_per_serving,"expected_max_diners":checked.expected_max_diners}
            if row_key in seen:
                first,number=seen[row_key]
                if fingerprint!=first:
                    fail(r,"ingredient","Conflicting menu ingredient rows for the same date/meal/menu/ingredient; no quantity inferred")
                duplicates.append({"key":{"date":checked.date.isoformat(),"meal_type":checked.meal_type,"menu_name":checked.menu_name,"ingredient":amount.ingredient},"row":r.number,"original_row":number})
                continue
            seen[row_key]=(fingerprint,r.number)
            key = (r["date"], r["meal_type"], r["menu_name"])
            m = grouped.setdefault(key, dict(date=r["date"], meal_type=r["meal_type"], menu_name=r["menu_name"], expected_max_diners=r["expected_max_diners"], ingredients=[]))
            if m["expected_max_diners"] != r["expected_max_diners"]:
                fail(r,"expected_max_diners","Inconsistent diners for same menu")
            m["ingredients"].append(amount)
        self.menus = [Menu(**v) for v in grouped.values()]
        if duplicates:
            self.validation_warnings.append({"type":"duplicate_menu_rows","message":"동일 식단 중복 행을 분석용 복사본에서 제외했습니다. 원본 파일은 변경하지 않았습니다.",
                "duplicate_count":len(duplicates),"keys":[x["key"] for x in duplicates],"rows":[{"row":x["row"],"original_row":x["original_row"]} for x in duplicates],"file":str(directory/"weekly_menu.xlsx")})
    def get_inventory(self):
        return [x.model_copy(deep=True) for x in self.inventory]
    def get_weekly_menu(self):
        return [x.model_copy(deep=True) for x in self.menus]
    def get_validation_warnings(self):
        from copy import deepcopy
        return deepcopy(self.validation_warnings)
