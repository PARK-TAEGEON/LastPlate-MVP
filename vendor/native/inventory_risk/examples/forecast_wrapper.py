"""Inject an already-produced forecast into a copied analysis snapshot only."""
from dataclasses import replace
from datetime import date
from pydantic import Field, StrictInt
from schemas.models import Model
from schemas.errors import input_error
from agents.inventory_risk import analyze_inventory_and_risk

class ForecastRow(Model):
    date: date
    meal_type: str
    expected_max_diners: StrictInt = Field(ge=0)

class ForecastSnapshot(Model):
    forecast_version: str = Field(min_length=1)
    input_snapshot_id: str = Field(min_length=1)
    rows: list[ForecastRow] = Field(min_length=1)

class ForecastInventoryAdapter:
    def __init__(self, base, forecast):
        self.base=base
        self.forecast=ForecastSnapshot.model_validate(forecast)
        self.source=base.source
        self.menu_source=base.menu_source+"; forecast="+self.forecast.forecast_version
        self.counts={}
        for row in self.forecast.rows:
            key=(row.date,row.meal_type)
            if key in self.counts:
                raise input_error("Duplicate forecast date/meal", "forecast.rows")
            self.counts[key]=row.expected_max_diners

    def get_inventory(self):
        return [lot.model_copy(deep=True) for lot in self.base.get_inventory()]

    def get_validation_warnings(self):
        return getattr(self.base,"get_validation_warnings",lambda:[])()

    def get_weekly_menu(self):
        menus=[]
        for original in self.base.get_weekly_menu():
            key=(original.date,original.meal_type)
            # No partial fallback to original counts: require full menu coverage.
            if key not in self.counts:
                raise input_error(f"Missing forecast for {key}", "forecast.rows")
            menu=original.model_copy(deep=True)
            menu.expected_max_diners=self.counts[key]
            menus.append(menu)
        return menus

def analyze_with_forecast(adapters, state, forecast, user_event=None):
    from pydantic import ValidationError
    from schemas.errors import DataQualityError,validation_error
    from agents.inventory_risk import error_report
    try:
        wrapper=ForecastInventoryAdapter(adapters.inventory,forecast)
        bundle=replace(adapters,inventory=wrapper)
        # Re-run full analysis after a supplied forecast; never calculate attendance.
        return analyze_inventory_and_risk({**state,"mode":"full","adapters":bundle,
            "forecast_version":wrapper.forecast.forecast_version,
            "input_snapshot_id":wrapper.forecast.input_snapshot_id},user_event)
    except DataQualityError as exc:
        return error_report(exc.detail,state,adapters.sources())
    except ValidationError as exc:
        return error_report(validation_error(exc,prefix="forecast.").detail,state,adapters.sources())
