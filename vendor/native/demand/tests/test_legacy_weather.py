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


def test_rain_not_required_when_explicitly_excluded():
    d = normalize(read_csv(ROOT/'data/processed/lunch.csv')).tail(10)
    w = read_csv(ROOT/'experiments/weather/data/processed/weather_daily.csv')
    d = merge_observed_weather(d,w)
    d['precipitation'] = np.nan
    d['rain'] = np.nan
    assert build_features(d,'D',SELECTED).notna().all().all()
    with pytest.raises(ValueError):
        build_features(d,'D')

