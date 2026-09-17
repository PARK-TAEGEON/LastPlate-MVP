from copy import deepcopy


MESSAGES = {
    'MODEL_INPUT_OUT_OF_RANGE': '현재 입력은 모델 학습범위를 벗어났습니다. 예측은 참고용이며 사업장별 데이터 축적 후 보정이 필요합니다.',
    'RECIPE_MISSING': '일부 메뉴의 레시피 기준량을 찾지 못했습니다.',
    'INVENTORY_DATA_MISSING': '재고 데이터가 없어 발주 검수 일부를 수행하지 못했습니다.',
    'UNIT_ERROR': '지원하지 않는 단위입니다. g 또는 kg를 사용하세요.',
    'CONSTRAINT_FAIL': '운영 기준을 만족하지 못하는 항목이 있습니다.',
    'DECISION_NEEDS_CONFIRMATION': '이벤트 또는 위험 정보에 운영자 확인이 필요합니다.',
}


def message(row):
    value = deepcopy(row)
    if value.get('code') in MESSAGES:
        value['original_message'] = value.get('message')
        value['message'] = MESSAGES[value['code']]
    return value


def demand(raw, request):
    result = deepcopy(raw)
    a = request.attendance
    result['available_population'] = a.registered_population - a.vacation - a.business_trip - a.work_from_home
    result['warnings'] = [message(w) for w in result['warnings']]
    return result


def operation(raw):
    result = deepcopy(raw)
    percent = raw.get('safety_margin_pct')
    result['safety_margin'] = percent / 100 if percent is not None else None
    return result
