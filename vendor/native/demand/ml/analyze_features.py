import argparse
from pathlib import Path
import pandas as pd
from .config import ROOT, MENU_RULES
from .prepare_data import read_csv, normalize
from .feature_engineering import build_features

def analyze(root=ROOT):
    root = Path(root)
    d = normalize(read_csv(root / 'data/processed/lunch.csv'))
    out = root / 'reports'
    out.mkdir(parents=True, exist_ok=True)
    # Descriptive whole-history tables; not target encodings or model inputs.
    d.groupby('weekday').agg(n=('actual_diners', 'size'), mean_diners=('actual_diners', 'mean'),
                            mean_participation=('participation_rate', 'mean'),
                            std_participation=('participation_rate', 'std')).reindex(list('월화수목금토일')).dropna(how='all').to_csv(out / 'weekday_patterns.csv', encoding='utf-8-sig')
    x = build_features(d, 'C')
    rows = []
    for feature in MENU_RULES:
        for flag in (0, 1):
            g = d.loc[x[feature] == flag]
            rows.append(dict(feature=feature, present=flag, n=len(g),
                             mean_diners=g.actual_diners.mean(), mean_participation=g.participation_rate.mean()))
    pd.DataFrame(rows).to_csv(out / 'menu_patterns.csv', index=False, encoding='utf-8-sig')
    sensitivity = pd.DataFrame({'date': d.date, 'estimated_available': d.available_population,
                                'rate_subtracting_remote': d.participation_rate,
                                'rate_without_remote_subtraction': d.actual_diners / (d.employees-d.vacation-d.business_trip)})
    sensitivity.to_csv(out / 'participation_sensitivity.csv', index=False)

def export_shap(root=ROOT, limit=200):
    """Optional dependency: pip install shap. Descriptive training-data explanation."""
    import shap
    import numpy as np
    from .model_registry import ModelRegistry
    root = Path(root)
    bundle, _ = ModelRegistry(root / 'models').load()
    d = normalize(read_csv(root / 'data/processed/lunch.csv')).tail(limit)
    if bundle['group'] == 'D':
        from .weather import merge_observed_weather
        d = merge_observed_weather(d, read_csv(root / 'data/processed/weather_daily.csv'))
    x = build_features(d, bundle['group'], bundle.get('weather_features'))
    values = shap.TreeExplainer(bundle['model']).shap_values(x)
    pd.DataFrame({'feature': x.columns, 'mean_absolute_shap': np.abs(values).mean(axis=0)}).to_csv(root / 'reports/shap.csv', index=False)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--shap', action='store_true')
    args = p.parse_args()
    analyze(args.root)
    if args.shap:
        export_shap(args.root)
