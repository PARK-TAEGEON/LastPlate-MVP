"""Compute and persist demo recommendations, never real orders/reservations."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_CEILING
from uuid import uuid4

from lastplate_backend.engine import calculate_decision, DecisionValidationError
from lastplate_backend.repositories import OperationPlanRepository
from lastplate_backend.schemas import OperationPlanRequest, OperationPlanResponse, PurchaseRecommendation, Alert
from lastplate_backend.services.inventory_planning import stock_snapshot, allocate_lots

WARNING_MESSAGES = {
    'NEGATIVE_DEMAND_CLIPPED_TO_ZERO': '인원 감소 후 예측이 음수가 되어 0명으로 보정했습니다.',
    'MISSING_INGREDIENT_TREATED_AS_ZERO': '입력에 없는 식재료는 재고 0kg으로 계산했습니다.',
    'SOME_LOCKED_QUANTITIES_ASSUMED_FROM_PLAN': '시작된 배치의 실적이 없어 기존 계획량으로 잠갔습니다.',
    'EQUIPMENT_CAPACITY_SHORTAGE': '설비 용량이 적용 조리량보다 작습니다.',
    'INVENTORY_SHORTAGE': '현재 가용 재고만으로는 적용 조리량을 충족하지 못합니다.',
    'CONSTRAINT_VIOLATION': '입력된 최소 제공량 또는 영양 기준을 충족하지 못합니다.',
    'BELOW_RECOMMENDED_TARGET': '수동 적용량이 엔진 권장량보다 작습니다. 부족 위험을 검토하세요.',
    'LOCKED_BATCH_SURPLUS': '이미 시작된 배치가 있어 감축할 수 없는 초과분이 있습니다.',
}


class OperationPlanService:
    def __init__(self, repository: OperationPlanRepository):
        self.repository = repository

    @staticmethod
    def _calculate(payload, stock):
        result = calculate_decision(
            prediction=payload['forecast'], events=payload['events'], menus=payload['menus'],
            current_time=payload['current_time'], inventory_kg=stock, policy=payload['policy'],
            constraints=payload['constraints'], applied_servings=payload.get('applied_servings'))
        result['events'] = payload['events']
        result['forecast_metadata'] = payload['forecast']
        result['operating_rules_verified'] = payload['policy']['operating_rules_verified']
        return result

    @staticmethod
    def _purchases(decision, payload):
        inventory = {item['ingredient']: item for item in payload['inventory']}
        now = datetime.fromisoformat(payload['current_time'])
        purchases = []
        for row in decision['inventory']:
            shortage = Decimal(str(row['additional_kg_for_equipment_plan']))
            if shortage <= 0:
                continue
            item = inventory.get(row['ingredient'], {})
            unit = Decimal(str(item.get('order_unit_kg', .001)))
            count = int((shortage/unit).to_integral_value(rounding=ROUND_CEILING))
            order = count * unit
            deadlines = [datetime.fromisoformat(batch['start']) for menu in decision['menus']
                         if row['ingredient'] in menu['recipe_g'] for batch in menu['future']
                         if batch['desired_qty'] > 0]
            required_by = min(deadlines) if deadlines else None
            arrival = datetime.fromisoformat(item['expected_delivery_at']) if item.get('expected_delivery_at') else None
            delivery = ('late' if arrival and required_by and arrival > required_by else
                        'on_time' if arrival and required_by and now < arrival <= required_by else 'unconfirmed')
            price = item.get('unit_price_per_kg')
            purchases.append(PurchaseRecommendation(
                ingredient=row['ingredient'], shortage_kg=float(shortage), order_unit_kg=float(unit),
                recommended_order_kg=float(order), package_count=count,
                estimated_cost=float(order*Decimal(str(price))) if price is not None else None,
                reason='설비로 조리 가능한 계획량 기준 부족분을 포장 단위로 올림. 실제 발주 전 납기 확인 필요.',
                delivery_status=delivery, expected_delivery_at=arrival, required_by=required_by))
        return purchases

    def create(self, request: OperationPlanRequest, *, parent_plan_id=None):
        payload = request.model_dump(mode='json', exclude_none=True)
        stock, lots, advisories = stock_snapshot(payload)
        decision = self._calculate(payload, stock)
        decision['stock_basis'] = 'current_usable_stock'
        purchases = self._purchases(decision, payload)
        projected_stock = stock.copy()
        for purchase in purchases:
            if purchase.delivery_status == 'on_time':
                projected_stock[purchase.ingredient] = float(Decimal(str(projected_stock.get(purchase.ingredient, 0)))
                                                           + Decimal(str(purchase.recommended_order_kg)))
        projected = self._calculate(payload, projected_stock)
        projected['stock_basis'] = 'hypothetical_on_time_recommended_purchases'
        projected['assumed_purchases'] = [p.model_dump(mode='json') for p in purchases if p.delivery_status == 'on_time']
        alerts = [Alert(code=code, severity='warning', message=WARNING_MESSAGES[code]) for code in decision['warnings']]
        for purchase in purchases:
            alerts.append(Alert(code='PURCHASE_REQUIRED', severity='warning', ingredient=purchase.ingredient,
                                message=f'{purchase.ingredient}: 부족 {purchase.shortage_kg:g}kg, 권장 발주 {purchase.recommended_order_kg:g}kg.'))
            if purchase.delivery_status != 'on_time':
                alerts.append(Alert(code='DELIVERY_'+purchase.delivery_status.upper(), severity='critical',
                                    ingredient=purchase.ingredient, message=f'{purchase.ingredient}: 납기 지연 또는 미확인. 입고 가정에서 제외했습니다.'))
        if not request.policy.operating_rules_verified:
            alerts.append(Alert(code='OPERATING_RULES_UNVERIFIED', severity='critical', message='운영 기준이 확인되지 않아 검토 완료를 제한합니다.'))
        for warning in request.forecast.warnings:
            alerts.append(Alert(code='FORECAST_NOTICE', severity='warning', message=warning))
        allowed = (request.policy.operating_rules_verified and
                   not any(menu['shortage'] for menu in projected['menus']) and
                   not projected['constraints']['violations'] and
                   all(p.delivery_status == 'on_time' for p in purchases) and
                   decision['target'] >= decision['recommended_target'])
        response = OperationPlanResponse(
            id=str(uuid4()), parent_plan_id=parent_plan_id, created_at=datetime.now(timezone.utc),
            site_id=request.site_id, meal_date=request.meal_date, meal_type=request.meal_type,
            result=decision, projected_after_purchase=projected, purchase_recommendations=purchases,
            alerts=alerts, inventory_advisories=advisories,
            stock_allocations=allocate_lots(lots, decision), review_allowed=allowed)
        self.repository.save(plan_id=response.id, parent_plan_id=parent_plan_id,
                             site_id=request.site_id, meal_date=request.meal_date.isoformat(), meal_type=request.meal_type,
                             created_at=response.created_at.isoformat(), request=payload, response=response.model_dump(mode='json'))
        return response

    @staticmethod
    def _restore(saved):
        if saved is None:
            return None
        response = dict(saved['response'])
        response.setdefault('meal_date', saved['request'].get('meal_date', saved['meal_date']))
        response.setdefault('meal_type', saved['request'].get('meal_type', saved['meal_type']))
        response.setdefault('inventory_advisories', [])
        return OperationPlanResponse.model_validate(response)

    def get(self, plan_id):
        return self._restore(self.repository.get(plan_id))

    def get_latest(self, *, site_id, meal_date: date, meal_type):
        return self._restore(self.repository.get_latest(site_id=site_id, meal_date=meal_date.isoformat(), meal_type=meal_type))

    def recalculate_with_event(self, plan_id, update):
        saved = self.repository.get(plan_id)
        if saved is None:
            return None
        payload = saved['request']
        if update.event.id in payload['forecast']['included_event_ids']:
            raise DecisionValidationError('이 이벤트가 포함되지 않은 기준 예측을 다시 생성한 후 변경하세요.')
        events = {event['id']: event for event in payload['events']}
        events[update.event.id] = update.event.model_dump(mode='json')
        payload['events'] = list(events.values())
        payload['current_time'] = update.current_time.isoformat()
        payload.pop('applied_servings', None)
        return self.create(OperationPlanRequest.model_validate(payload), parent_plan_id=plan_id)

    def adjust(self, plan_id, update):
        saved = self.repository.get(plan_id)
        if saved is None:
            return None
        payload = saved['request']
        payload['applied_servings'] = update.applied_servings
        payload['current_time'] = update.current_time.isoformat()
        return self.create(OperationPlanRequest.model_validate(payload), parent_plan_id=plan_id)

    def review(self, plan_id):
        return self._restore(self.repository.review(plan_id))
