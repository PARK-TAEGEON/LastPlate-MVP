from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 42
SCHEMA_VERSION = 1
FEATURE_RULES_VERSION = 'v2'
ALIASES = {
    '일자': 'date', '요일': 'weekday', '본사정원수': 'employees',
    '본사휴가자수': 'vacation', '본사출장자수': 'business_trip',
    '본사시간외근무명령서승인건수': 'overtime',
    '현본사소속재택근무자수': 'work_from_home', '중식메뉴': 'menu',
    '중식계': 'actual_diners', '석식계': 'dinner_diners',
}
STAFF = ['employees', 'vacation', 'business_trip', 'work_from_home', 'overtime']
WEATHER = ['temp_mean', 'temp_max', 'temp_min', 'precipitation', 'humidity', 'rain']
# Transparent heuristic indicators, not measured preference or main-dish labels.
MENU_RULES = {
    'menu_meat': r'제육|돈육|돼지|쇠고기|소고기|소불고기|돈불고기|닭|치킨|오리|삼겹|갈비|돈까스|돈가스|함박|미트',
    'menu_fish': r'고등어|삼치|갈치|꽁치|명태|동태|황태|대구|연어|가자미|생선|참치|조기|임연수',
    'menu_noodles': r'국수|우동|라면|냉면|쫄면|파스타|스파게티|짜장면|짬뽕|소바|당면',
    'menu_special': r'특식|특별|\(New\)|스테이크|장어|삼계탕',
    'menu_rice_bowl': r'볶음밥|덮밥|비빔밥|오므라이스',
    'menu_soup': r'국|찌개|탕|전골',
}
MENU_RULES_V2 = dict(MENU_RULES, menu_meat=MENU_RULES['menu_meat'] + r'|불고기',
                     menu_soup=r'국(?!수|산|내)|찌개|탕|전골')

def weather_feature_names(selected=None):
    selected = WEATHER.copy() if selected is None else list(selected)
    if not selected or len(set(selected)) != len(selected) or not set(selected).issubset(WEATHER):
        raise ValueError('Choose nonempty, unique, supported weather features')
    return selected

def feature_names(group, weather_features=None):
    if group not in 'ABCD' or len(group) != 1:
        raise ValueError('group must be A, B, C or D')
    names = STAFF.copy()
    if group in 'BCD':
        names += [f'weekday_{i}' for i in range(7)]
    if group in 'CD':
        names += list(MENU_RULES)
    if group == 'D':
        names += weather_feature_names(weather_features)
    return names
