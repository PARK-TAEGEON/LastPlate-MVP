import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
from .config import ROOT, SEED, feature_names, WEATHER, weather_feature_names
from .prepare_data import read_csv, normalize
from .feature_engineering import build_features, features_for_bundle
from .provenance import training_provenance
from .evaluate import metrics, predictions
from .model_registry import ModelRegistry, atomic_json
from .weather import merge_observed_weather

def make_model(kind):
    if kind == 'lightgbm':
        return LGBMRegressor(n_estimators=350, learning_rate=0.035, num_leaves=15,
                             min_child_samples=25, reg_lambda=2, random_state=SEED,
                             n_jobs=2, verbosity=-1, deterministic=True,
                             force_col_wise=True, importance_type='gain')
    if kind == 'xgboost':
        return XGBRegressor(n_estimators=350, learning_rate=0.035, max_depth=4,
                            min_child_weight=10, reg_lambda=2, random_state=SEED,
                            n_jobs=2, tree_method='hist', objective='reg:squarederror', importance_type='gain')
    raise ValueError('Unknown model family')

def period(d):
    return {'start': str(d.date.min().date()), 'end': str(d.date.max().date()), 'rows': len(d)}

def split_time(d):
    if len(d) < 100 or d.date.duplicated().any() or not d.date.is_monotonic_increasing:
        raise ValueError('Need >=100 unique, sorted dates')
    a, b = int(len(d) * .70), int(len(d) * .85)
    return d.iloc[:a].copy(), d.iloc[a:b].copy(), d.iloc[b:].copy()

def fit_bundle(d, kind, group, weather_features=None, rules_version='v2', include_overtime=True):
    model = make_model(kind)
    x = build_features(d, group, weather_features, rules_version, include_overtime)
    model.fit(x, d.actual_diners)
    bundle = dict(model=model, group=group, kind=kind, features=list(x.columns))
    bundle.update(feature_rules_version=rules_version, include_overtime=include_overtime,
                  provenance=training_provenance(d,rules_version))
    if group == 'D':
        bundle['weather_features'] = weather_feature_names(weather_features)
    return bundle

def bundle_predict(bundle, d):
    return predictions(bundle['model'], features_for_bundle(bundle,d))

def environment():
    return {p: importlib.metadata.version(p) for p in ['numpy', 'pandas', 'scikit-learn', 'lightgbm', 'xgboost', 'joblib', 'filelock']}

def train(root=ROOT, weather_daily=None, weather_features=None, common_weather_rows=False):
    root = Path(root)
    registry = ModelRegistry(root / 'models')
    if registry.current_version():
        raise ValueError('Model already exists. Use batch retrain; initial training cannot overwrite it.')
    source = root / 'data/processed/lunch.csv'
    d = normalize(read_csv(source))
    selected_weather = weather_feature_names(weather_features)
    original_splits = split_time(d)
    val_start = original_splits[1].date.min()
    test_start = original_splits[2].date.min()
    excluded_dates = []
    groups = list('ABC')
    weather_status = 'D skipped: no aligned, complete weather supplied.'
    if weather_daily:
        d = merge_observed_weather(d, read_csv(weather_daily))
        complete = d[selected_weather].notna().all(axis=1)
        count = int(complete.sum())
        if common_weather_rows:
            excluded_dates = d.loc[~complete, 'date'].dt.strftime('%Y-%m-%d').tolist()
            d = d.loc[complete].reset_index(drop=True)
            if d.empty:
                raise ValueError('No complete common weather rows')
        if count == len(d):
            groups.append('D')
            weather_status = 'D enabled: prior-calendar-day observed weather, complete on all A/B/C/D rows.'
        else:
            weather_status = f'D skipped: {count}/{len(d)} rows have complete lag-1 weather. No subset comparison or fabricated weather.'
    elif common_weather_rows:
        raise ValueError('common_weather_rows requires a weather_daily source')
    # Freeze calendar boundaries before any weather-related row exclusions.
    train_d = d.loc[d.date < val_start].copy()
    val = d.loc[(d.date >= val_start) & (d.date < test_start)].copy()
    test = d.loc[d.date >= test_start].copy()
    if len(train_d) < 100 or min(len(val), len(test)) < 30:
        raise ValueError('Insufficient common rows in a frozen time split')
    reports = root / 'reports'
    reports.mkdir(parents=True, exist_ok=True)
    results, all_predictions, importance = [], [], []
    for kind in ('lightgbm', 'xgboost'):
        for group in groups:
            bundle = fit_bundle(train_d, kind, group, selected_weather)
            pred = bundle_predict(bundle, val)
            score = metrics(val.actual_diners, pred)
            results.append(dict(model=kind, group=group, **score))
            all_predictions.append(pd.DataFrame(dict(date=val.date, actual=val.actual_diners,
                                                    predicted=pred, model=kind, group=group)))
            gain = bundle['model'].feature_importances_.astype(float)
            for name, value in zip(bundle['features'], gain):
                importance.append(dict(model=kind, group=group, feature=name,
                                       gain=float(value), gain_share=float(value / gain.sum()) if gain.sum() else 0))
    scores = pd.DataFrame(results).sort_values(['mae', 'model', 'group'])
    scores.to_csv(reports / 'ablation.csv', index=False)
    pd.concat(all_predictions).to_csv(reports / 'validation_predictions.csv', index=False)
    pd.DataFrame(importance).to_csv(reports / 'feature_importance.csv', index=False)
    winner = scores.iloc[0]
    train_val = pd.concat([train_d, val], ignore_index=True)
    evaluated = fit_bundle(train_val, winner.model, winner.group, selected_weather)
    test_pred = bundle_predict(evaluated, test)
    test_score = metrics(test.actual_diners, test_pred)
    # Simple baselines fitted only to the same original training period.
    rate = float(train_d.actual_diners.sum() / train_d.available_population.sum())
    baselines = {'train_mean': metrics(val.actual_diners, np.repeat(round(train_d.actual_diners.mean()), len(val))),
                 'available_times_train_rate': metrics(val.actual_diners, np.rint(val.available_population * rate))}
    pd.DataFrame(dict(date=test.date, actual=test.actual_diners, predicted=test_pred,
                      residual=test.actual_diners - test_pred)).to_csv(reports / 'test_predictions.csv', index=False)
    # The selected model is refitted on all known labels for deployment only.
    deployed = fit_bundle(d, winner.model, winner.group, selected_weather)
    meta = dict(model_type=winner.model, train_period=period(d), trained_through=period(d)['end'],
                selection_train_period=period(train_d), validation_period=period(val), test_period=period(test),
                validation_metrics={k: v for k, v in winner.to_dict().items() if k not in ('model', 'group')},
                test_metrics=test_score, mae=test_score['mae'],
                evaluation_note='Test scored on train+validation fit. Deployment then refit on all dates; no independent score for that exact refit.',
                dependencies=environment(), model_parameters=deployed['model'].get_params(),
                data_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                weather_features=selected_weather if winner.group == 'D' else [],
                weather_source_sha256=hashlib.sha256(Path(weather_daily).read_bytes()).hexdigest() if weather_daily else None,
                excluded_dates=excluded_dates,
                weather_policy='prior_day_observed' if winner.group == 'D' else 'not_used')
    saved = registry.promote(deployed, meta)
    summary = dict(selected_model=winner.model, selected_group=winner.group,
                   validation_mae=float(winner.mae), test_metrics=test_score,
                   splits={'train': period(train_d), 'validation': period(val), 'test': period(test)},
                   baselines=baselines, weather=weather_status, model_version=saved['model_version'],
                   weather_features=selected_weather if weather_daily else [],
                   common_weather_rows=common_weather_rows, excluded_dates=excluded_dates,
                   original_splits={k:period(v) for k,v in zip(['train','validation','test'],original_splits)})
    atomic_json(reports / 'training_summary.json', summary)
    print(scores.to_string(index=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--weather-daily', type=Path)
    p.add_argument('--weather-features', nargs='+', choices=WEATHER)
    p.add_argument('--common-weather-rows', action='store_true')
    a = p.parse_args()
    train(a.root, a.weather_daily, a.weather_features, a.common_weather_rows)

if __name__ == '__main__':
    main()
