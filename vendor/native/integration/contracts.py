"""Public transport contracts. Native module payloads are retained as evidence."""
from pathlib import Path
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]

class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    storage_dir: Path = ROOT / 'runtime'
    mode: Literal['demo','replay','operation'] = 'demo'
    timezone: str = 'Asia/Seoul'
    cutoff_time: str = '10:00'
    actual_ready_time: str = '14:00'
    timeout_seconds: float = Field(default=120, gt=0)

class PipelineInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    request_id: str = Field(min_length=1,max_length=100)
    site_id: str = Field(min_length=1)
    target_date: str
    as_of: str
    meal_type: Literal['lunch'] = 'lunch'
    meal_capacity: int = Field(ge=0,strict=True)
    attendance: dict
    availability: dict | None = None
    weekly_menu: list[dict] = Field(min_length=1)
    recipes: list[dict]
    inventory: list[dict]
    planned_orders: list[dict]
    nutrition: list[dict]
    prices: list[dict]
    monthly_prices: list[dict]
    supply_events: list[dict]
    sources: dict[str,str]
    operation_policy: dict
    event: str | dict | None = None

    @model_validator(mode='after')
    def scope(self):
        from datetime import date
        if date.fromisoformat(self.as_of)>date.fromisoformat(self.target_date):
            raise ValueError('as_of must not exceed target_date')
        required={'recipe','inventory','nutrition','price_trend','monthly_price','supply_risk','weekly_menu','constraints'}
        if not required <= self.sources.keys() or any(not self.sources[k].strip() for k in required):
            raise ValueError('All data source declarations are required; no implicit DEMO fallback')
        for m in self.weekly_menu:
            if any(not isinstance(m.get(k),str) or not m[k].strip() for k in ('date','meal_type','menu_name')):
                raise ValueError('Each weekly_menu row requires date, meal_type and menu_name strings')
            date.fromisoformat(m['date'])
        keys=[(m['date'],m['meal_type'],m['menu_name']) for m in self.weekly_menu]
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate weekly menu date/meal/name')
        if not any(k[:2]==(self.target_date,self.meal_type) for k in keys):
            raise ValueError('No menu for requested service')
        names=[]
        for recipe in self.recipes:
            if not isinstance(recipe.get('menu_name'),str) or not isinstance(recipe.get('ingredients'),list):
                raise ValueError('Each recipe requires menu_name and ingredients list')
            names.append(recipe['menu_name'])
            for ingredient in recipe['ingredients']:
                if not isinstance(ingredient,dict): raise ValueError('Each recipe ingredient must be an object')
                for key in ('ingredient','amount_per_serving','unit'):
                    if key not in ingredient: raise ValueError('Recipe ingredient missing '+key)
                if not isinstance(ingredient['ingredient'],str): raise ValueError('Ingredient name must be a string')
        if len(names)!=len(set(names)): raise ValueError('Duplicate recipe name')
        for lot in self.inventory:
            for key in ('ingredient','current_stock','unit','expiry_date'):
                if key not in lot: raise ValueError('Inventory lot missing '+key)
            if not isinstance(lot['expiry_date'],str): raise ValueError('expiry_date must be YYYY-MM-DD')
            date.fromisoformat(lot['expiry_date'])
        return self

class DemandResult(BaseModel):
    prediction_id: str
    target_date: str
    predicted_diners: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    predicted_rate: float | None = None
    available_population: float | None = None
    model_version: str
    model_type: str | None = None
    applicability: Literal['IN_RANGE','OUT_OF_DISTRIBUTION','UNKNOWN']
    confidence: Literal['LOW','UNKNOWN']
    warnings: list[dict] = Field(default_factory=list)
    training_ranges: dict = Field(default_factory=dict)
    source_type: Literal['MODEL'] = 'MODEL'
    source_payload: dict

class PipelineResult(BaseModel):
    pipeline_status: Literal['COMPLETE','PARTIAL','FAILED']
    demand: dict | None = None
    operation: dict | None = None
    inventory_risk: dict | None = None
    decision: dict | None = None
    errors: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    timings: dict[str,float] = Field(default_factory=dict)
    input_revision: str | None = None
    advisory_only: Literal[True] = True
