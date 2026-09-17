"""Explicit, reproducible simulation inputs; not live business data."""
from typing import Literal
from fastapi import APIRouter
from lastplate_backend.schemas import OperationPlanRequest

router = APIRouter(prefix='/api/v1/demo', tags=['demo'])


@router.get('/input', response_model=OperationPlanRequest)
def demo_input(scenario: Literal['normal', 'capacity_limit', 'delivery_delay', 'no_doc'] = 'normal'):
    capacity = 500 if scenario == 'capacity_limit' else 550
    arrival = '2026-09-18T12:00:00+09:00' if scenario == 'delivery_delay' else '2026-09-18T08:00:00+09:00'
    return OperationPlanRequest.model_validate({
        'site_id': 'A사업장', 'meal_date': '2026-09-18', 'meal_type': 'lunch',
        'current_time': '2026-09-17T18:00:00+09:00',
        'forecast': {'site_id': 'A사업장', 'meal_date': '2026-09-18', 'meal_type': 'lunch',
                     'lower': 450, 'mid': 480, 'upper': 510, 'model_version': 'ui-demo-fixture-v1',
                     'interval_method': 'demo_interval', 'source_kind': 'demo',
                     'warnings': ['450~510은 UI 시연용 범위이며 통계적 신뢰수준이 없습니다.']},
        'policy': {'target_method': 'max_interval_and_buffer', 'safety_buffer_people': 10,
                   'cooking_unit': 10, 'operating_rules_verified': scenario != 'no_doc'},
        'menus': [{'name': name, 'recipe_g': {ingredient: grams},
                   'batches': [{'name': '1차 조리', 'start': '2026-09-18T10:00:00+09:00',
                                'planned': min(510, capacity), 'capacity': capacity}]}
                  for name, ingredient, grams in [('쌀밥', '쌀', 100), ('제육볶음', '돼지고기', 120), ('양배추무침', '양배추', 40)]],
        'inventory': [
            {'ingredient': '쌀', 'available_kg': 60, 'order_unit_kg': 10, 'expected_delivery_at': arrival},
            {'ingredient': '돼지고기', 'physical_kg': 50, 'reserved_kg': 5, 'order_unit_kg': 5,
             'unit_price_per_kg': 12000, 'expected_delivery_at': arrival},
            {'ingredient': '양배추', 'lots': [
                {'id': '양배추-A', 'quantity_kg': 10, 'expires_on': '2026-09-18'},
                {'id': '양배추-B', 'quantity_kg': 15, 'expires_on': '2026-09-21'}],
             'order_unit_kg': 5, 'expected_delivery_at': arrival}],
    })
