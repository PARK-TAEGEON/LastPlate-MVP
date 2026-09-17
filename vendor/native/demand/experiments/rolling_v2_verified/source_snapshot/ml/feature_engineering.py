import re
import numpy as np
import pandas as pd
from .config import STAFF, WEATHER, MENU_RULES, MENU_RULES_V2, feature_names, weather_feature_names

def menu_features(menu, rules_version='v2'):
    # Remove origin annotations to avoid e.g. 국 in 국내산 triggering soup.
    cleaned = re.sub(r'\([^)]*(?:원산지|국내산|수입산|호주산|미국산)[^)]*\)', '', menu)
    if rules_version not in ('v1','v2'):
        raise ValueError('Unknown menu rules version')
    rules = MENU_RULES if rules_version == 'v1' else MENU_RULES_V2
    return {name: int(bool(re.search(pattern, cleaned, flags=re.I))) for name, pattern in rules.items()}

def build_features(d, group, weather_features=None, rules_version='v2', include_overtime=True):
    staff = STAFF if include_overtime else [c for c in STAFF if c != 'overtime']
    x = d[staff].copy()
    if group in 'BCD':
        day = pd.to_datetime(d['date']).dt.dayofweek
        for i in range(7):
            x[f'weekday_{i}'] = (day == i).astype(int)
    if group in 'CD':
        m = pd.DataFrame([menu_features(v, rules_version) for v in d['menu']], index=d.index)
        x = pd.concat([x, m], axis=1)
    if group == 'D':
        selected = weather_feature_names(weather_features)
        missing = set(selected) - set(d)
        if missing:
            raise ValueError(f'Missing weather fields: {sorted(missing)}')
        for c in selected:
            x[c] = pd.to_numeric(d[c], errors='raise')
            if not np.isfinite(x[c]).all():
                raise ValueError('D requires complete weather on the same comparison rows')
    names = feature_names(group, weather_features)
    if not include_overtime:
        names.remove('overtime')
    return x[names].astype(float)

def features_for_bundle(bundle, d):
    return build_features(d, bundle['group'], bundle.get('weather_features'),
                          bundle.get('feature_rules_version','v1'), bundle.get('include_overtime',True))
