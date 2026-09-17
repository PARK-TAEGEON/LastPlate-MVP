"""Regression coverage for multiple weather sources and selected D features."""
import json
import numpy as np
import pandas as pd
import pytest
from ml.config import ROOT, STAFF, feature_names
from ml.prepare_data import read_csv, normalize
from ml.weather import combine_hourly, merge_observed_weather
from ml.feature_engineering import build_features
from ml.train import fit_bundle, bundle_predict
from ml.model_registry import ModelRegistry
from tools.demand import predict_demand, record_actual_result
from ml.retrain import batch_retrain

SELECTED = ['temp_mean','temp_max','temp_min','humidity']

def test_combine_exact_duplicates_and_conflicts():
    # Explicit synthetic schema fixture, not model evaluation observations.
    a = pd.DataFrame({'지점':[192], '일시':['2020-01-01 00:00'], '기온(°C)':[1.]})
    merged, duplicates = combine_hourly([a, a.copy()])
    assert len(merged) == 1 and duplicates == 1
    b = a.copy(); b['기온(°C)'] = 2
    with pytest.raises(ValueError, match='Conflicting'):
        combine_hourly([a,b])

@pytest.mark.parametrize('selected', [[], ['humidity','humidity'], ['invented_weather']])
def test_invalid_weather_selection(selected):
    with pytest.raises(ValueError):
        feature_names('D',selected)

def test_same_validation_rows_for_all_eight_actual_models():
    path = ROOT / 'experiments/weather/reports'
    p = read_csv(path / 'validation_predictions.csv')
    scores = read_csv(path / 'ablation.csv')
    original_dates = read_csv(ROOT / 'reports/validation_predictions.csv').query("model == 'lightgbm' and group == 'C'").date.tolist()
    assert len(scores) == 8
    for row in scores.itertuples():
        g = p[(p.model == row.model) & (p.group == row.group)]
        assert g.date.tolist() == original_dates
        assert abs((g.actual-g.predicted).abs().mean()-row.mae) < 1e-10
    s = json.loads((path/'training_summary.json').read_text(encoding='utf-8'))
    assert s['splits']['train']['end'] < s['splits']['validation']['start']
    assert s['splits']['validation']['end'] < s['splits']['test']['start']
    assert s['splits']['train']['rows'] == 834
    assert len(s['excluded_dates']) == 9
    assert s['weather_features'] == SELECTED

def test_selected_weather_roundtrip_inference_and_record(tmp_path):
    d = normalize(read_csv(ROOT/'data/processed/lunch.csv'))
    w = read_csv(ROOT/'experiments/weather/data/processed/weather_daily.csv')
    joined = merge_observed_weather(d,w)
    complete = joined.loc[joined[SELECTED].notna().all(axis=1)].head(130)
    bundle = fit_bundle(complete.iloc[:100], 'lightgbm', 'D', SELECTED)
    assert 'precipitation' not in bundle['features']
    r = ModelRegistry(tmp_path/'models')
    r.promote(bundle, {'trained_through':str(complete.iloc[99].date.date())})
    row = complete.iloc[100]
    inputs = {k:float(row[k]) for k in STAFF+SELECTED}
    inputs.update(date=str(row.date.date()),menu=row.menu)
    p = predict_demand(inputs,r.path)
    assert set(SELECTED).issubset(p['input_data'])
    assert 'rain' not in p['input_data']
    assert p['prediction'] == int(bundle_predict(bundle,complete.iloc[100:101])[0])
    record_actual_result(p,int(row.actual_diners),history_path=tmp_path/'history.csv',model_dir=r.path)
    assert len(read_csv(tmp_path/'history.csv')) == 1

def test_rain_not_required_when_explicitly_excluded():
    d = normalize(read_csv(ROOT/'data/processed/lunch.csv')).tail(10)
    w = read_csv(ROOT/'experiments/weather/data/processed/weather_daily.csv')
    d = merge_observed_weather(d,w)
    d['precipitation'] = np.nan
    d['rain'] = np.nan
    assert build_features(d,'D',SELECTED).notna().all().all()
    with pytest.raises(ValueError):
        build_features(d,'D')

def test_real_d_batch_with_missing_historical_weather(tmp_path):
    d = normalize(read_csv(ROOT/'data/processed/lunch.csv'))
    w = read_csv(ROOT/'experiments/weather/data/processed/weather_daily.csv')
    joined = merge_observed_weather(d,w)
    out = tmp_path/'data/processed'
    out.mkdir(parents=True)
    d.head(100).to_csv(out/'lunch.csv',index=False)
    w.to_csv(out/'weather_daily.csv',index=False)
    train = joined.head(100)
    train = train.loc[train[SELECTED].notna().all(axis=1)]
    r = ModelRegistry(tmp_path/'models')
    bundle = fit_bundle(train,'lightgbm','D',SELECTED)
    r.promote(bundle, {'trained_through':str(d.iloc[99].date.date()),
                       'weather_policy':'prior_day_observed'})
    for _,row in joined.iloc[100:130].iterrows():
        inputs = {k:float(row[k]) for k in STAFF+SELECTED}
        inputs.update(date=str(row.date.date()),menu=row.menu)
        p = predict_demand(inputs,r.path)
        record_actual_result(p,int(row.actual_diners),
                             history_path=tmp_path/'data/operational_history.csv',model_dir=r.path)
    result = batch_retrain(tmp_path)
    assert result['status'] in {'promoted','kept_incumbent'}
    assert result['candidate_train_period']['rows'] == len(train)+20
    assert result['gate_period']['rows'] == 10
    current,_ = r.load()
    assert current['weather_features'] == SELECTED
