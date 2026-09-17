"""Tests use temporary registries/history. No demo results enter real outputs."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyRegressor
from ml.config import ROOT, STAFF, WEATHER, feature_names
from ml.prepare_data import load_lh, normalize, correct_source_weekdays, read_csv
from ml.feature_engineering import menu_features, build_features
from ml.evaluate import metrics, monitoring
from ml.model_registry import ModelRegistry
from ml.train import split_time
from ml.weather import aggregate_hourly, merge_observed_weather
from ml.retrain import should_promote, batch_retrain
from tools.demand import predict_demand, record_actual_result, read_history

@pytest.fixture
def data():
    return normalize(read_csv(ROOT / 'data/processed/lunch.csv'))

def dummy_bundle(d, constant=0):
    model = DummyRegressor(strategy='constant', constant=constant).fit(build_features(d, 'A'), d.actual_diners)
    return dict(model=model, kind='lightgbm', group='A', features=feature_names('A'))

@pytest.fixture
def sandbox(tmp_path, data):
    (tmp_path / 'data/processed').mkdir(parents=True)
    data.head(100).to_csv(tmp_path / 'data/processed/lunch.csv', index=False)
    r = ModelRegistry(tmp_path / 'models')
    meta = r.promote(dummy_bundle(data.head(100)), dict(trained_through=str(data.iloc[99].date.date()), weather_policy='not_used'))
    return tmp_path, r, meta

def input_row(r):
    return dict(date=str(r.date.date()), menu=r.menu, **{c: float(r[c]) for c in STAFF})

def populate_history(root, registry, data):
    # Real LH rows replayed only in a temporary test directory; never service history.
    for _, row in data.iloc[100:130].iterrows():
        p = predict_demand(input_row(row), registry.path)
        record_actual_result(p, int(row.actual_diners), history_path=root / 'data/operational_history.csv', model_dir=registry.path)

def test_real_source_schema_and_audited_correction(data):
    raw = load_lh(ROOT / 'data/raw/lh_original.zip')
    fixed, changes = correct_source_weekdays(raw)
    assert changes == [{'date': '2018-06-01', 'supplied': '월', 'corrected': '금'}]
    assert len(normalize(fixed)) == len(data) == 1205
    assert raw['일자'].duplicated().sum() == 0
    assert '중식계' in raw and '석식계' in raw

@pytest.mark.parametrize('change', [dict(weekday='월', date='2026-09-20'), dict(overtime=None),
                                  dict(employees=-1), dict(vacation=float('inf')),
                                  dict(work_from_home=100000), dict(menu=' ')])
def test_invalid_serving_inputs(data, change):
    x = input_row(data.iloc[0]); x.update(change)
    with pytest.raises((ValueError, TypeError)):
        normalize(pd.DataFrame([x]), require_target=False)

def test_missing_overtime_and_duplicate_date(data):
    x = input_row(data.iloc[0]); del x['overtime']
    with pytest.raises(ValueError, match='Missing'):
        normalize(pd.DataFrame([x]), require_target=False)
    with pytest.raises(ValueError, match='Duplicate'):
        normalize(pd.concat([data.head(1)] * 2))

def test_time_split_no_overlap_or_target_features(data):
    train, val, test = split_time(data)
    assert train.date.max() < val.date.min() <= val.date.max() < test.date.min()
    for group in 'ABC':
        x = build_features(train, group)
        assert not {'actual_diners', 'participation_rate', 'dinner_diners'} & set(x)
        changed = train.copy(); changed['actual_diners'] = 999999
        pd.testing.assert_frame_equal(x, build_features(changed, group))

def test_menu_indicators_and_origin():
    x = menu_features('제육볶음 된장국 고등어구이 우동 덮밥 (New) 스테이크')
    assert all(x.values())
    assert menu_features('쌀밥 (쌀:국내산)')['menu_soup'] == 0

def test_weather_no_overlap_and_no_imputed_zero(data):
    raw = read_csv(ROOT / 'data/raw/weather_hourly.csv')
    daily = aggregate_hourly(raw)
    merged = merge_observed_weather(data, daily)
    assert merged[WEATHER].isna().all().all()
    assert daily.precipitation.isna().all()
    with pytest.raises(ValueError):
        merge_observed_weather(data, daily, lag_days=0)
    with pytest.raises(ValueError):
        build_features(merged, 'D')

def test_weather_complete_daily_join(data):
    date = data.date.iloc[0] - pd.Timedelta(days=1)
    # Explicitly synthetic weather fixture tests aggregation, not ablation.
    raw = pd.DataFrame({'지점': 192, '일시': pd.date_range(date, periods=24, freq='h'),
                        '기온(°C)': np.arange(24), '강수량(mm)': 0., '습도(%)': 50.})
    daily = aggregate_hourly(raw)
    joined = merge_observed_weather(data.head(1), daily)
    assert joined.temp_mean.iloc[0] == 11.5
    assert joined.precipitation.iloc[0] == 0
    assert list(build_features(joined, 'D')) == feature_names('D')

def test_metrics_zeros_and_monitoring():
    score = metrics([0, 10], [2, 8])
    assert score['mae'] == 2 and score['mape_pct'] == 20
    assert score['mape_excluded_zeros'] == 1
    assert monitoring(pd.DataFrame())['overall_mae'] is None
    h = pd.DataFrame({'date': pd.date_range('2024-01-01', periods=60),
                       'actual_diners': [11]*30 + [20]*30, 'predicted_diners': 10})
    assert monitoring(h)['retraining_needed']
    assert not monitoring(h.head(30))['retraining_needed']


def test_registry_archive_and_optimistic_lock(sandbox, data):
    root, r, meta = sandbox
    new = r.promote(dummy_bundle(data.head(100), 1), dict(trained_through='2016-06-01'), expected_current=meta['model_version'])
    assert r.load()[1]['model_version'] == new['model_version']
    assert (r.path / 'archive' / meta['model_version'] / 'demand_model.pkl').exists()
    with pytest.raises(RuntimeError):
        r.promote(dummy_bundle(data.head(100)), {}, expected_current=meta['model_version'])
    artifact = r.path / 'releases' / new['model_version'] / 'demand_model.pkl'
    artifact.write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='checksum'):
        r.load()




@pytest.mark.parametrize('old,new,margin,expected', [(10,10,0,False),(10,9,0,True),(10,11,0,False),(10,9,2,False)])
def test_strict_improvement(old, new, margin, expected):
    assert should_promote(old,new,margin) is expected
