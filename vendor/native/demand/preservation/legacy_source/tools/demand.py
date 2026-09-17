"""Small service-facing API; no web, LLM, or automatic training dependencies."""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from filelock import FileLock
from ml.config import ROOT, STAFF, WEATHER
from ml.prepare_data import normalize, read_csv
from ml.feature_engineering import build_features
from ml.evaluate import predictions, monitoring
from ml.model_registry import ModelRegistry

HISTORY_COLUMNS = ['prediction_id', 'date', 'model_version', 'predicted_at', 'recorded_at',
                   'predicted_diners', 'actual_diners', 'prediction_error', 'menu',
                   'available_population', 'input_json', 'weather_json', 'event_json',
                   'prepared_servings', 'leftover_servings']

def predict_demand(input_data, model_dir=None):
    registry = ModelRegistry(model_dir or ROOT / 'models')
    bundle, meta = registry.load()
    d = normalize(pd.DataFrame([input_data]), require_target=False)
    x = build_features(d, bundle['group'], bundle.get('weather_features'))
    prediction = int(predictions(bundle['model'], x)[0])
    fields = STAFF + ['weekday', 'menu'] + (bundle.get('weather_features', WEATHER) if bundle['group'] == 'D' else [])
    snapshot = {k: d.iloc[0][k].item() if isinstance(d.iloc[0][k], np.generic) else d.iloc[0][k] for k in fields}
    snapshot['date'] = str(d.iloc[0]['date'].date())
    return dict(prediction=prediction, model_version=meta['model_version'],
                prediction_id=uuid.uuid4().hex, predicted_at=datetime.now(timezone.utc).isoformat(),
                input_data=snapshot)

def read_history(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    return read_csv(path)

def _count(value, name, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)) or not np.isfinite(value) or value < 0 or value != int(value):
        raise ValueError(f'{name} must be a finite nonnegative integer')
    return int(value)

def record_actual_result(prediction, actual_diners, *, prepared_servings=None,
                         leftover_servings=None, weather=None, event_variables=None,
                         history_path=None, model_dir=None):
    """Keep the exact prediction-time inputs; duplicate dates/IDs are rejected.

    weather/event_variables are actual-time observations for future research,
    never silently copied into training inputs.
    """
    required = {'prediction', 'model_version', 'prediction_id', 'predicted_at', 'input_data'}
    if not required.issubset(prediction):
        raise ValueError('Pass the complete object returned by predict_demand')
    actual = _count(actual_diners, 'actual_diners')
    predicted = _count(prediction['prediction'], 'prediction')
    prepared = _count(prepared_servings, 'prepared_servings', True)
    leftover = _count(leftover_servings, 'leftover_servings', True)
    if prepared is not None and leftover is not None and leftover > prepared:
        raise ValueError('leftover_servings cannot exceed prepared_servings')
    d = normalize(pd.DataFrame([prediction['input_data']]), require_target=False)
    bundle, _ = ModelRegistry(model_dir or ROOT / 'models').load(prediction['model_version'])
    expected = int(predictions(bundle['model'], build_features(d, bundle['group'], bundle.get('weather_features')))[0])
    if expected != predicted:
        raise ValueError('Prediction and stored input snapshot do not match this model')
    row = dict(prediction_id=prediction['prediction_id'], date=str(d.date.iloc[0].date()),
               model_version=prediction['model_version'], predicted_at=prediction['predicted_at'],
               recorded_at=datetime.now(timezone.utc).isoformat(), predicted_diners=predicted,
               actual_diners=actual, prediction_error=actual-predicted, menu=d.menu.iloc[0],
               available_population=float(d.available_population.iloc[0]),
               input_json=json.dumps(prediction['input_data'], ensure_ascii=False, allow_nan=False),
               weather_json=json.dumps(weather, ensure_ascii=False, allow_nan=False),
               event_json=json.dumps(event_variables, ensure_ascii=False, allow_nan=False),
               prepared_servings=prepared, leftover_servings=leftover)
    path = Path(history_path or ROOT / 'data/operational_history.csv')
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + '.lock'):
        old = read_history(path)
        if not old.empty and ((old.date == row['date']).any() or (old.prediction_id == row['prediction_id']).any()):
            raise ValueError('A lunch actual already exists for this date or prediction ID')
        result = pd.concat([old, pd.DataFrame([row])], ignore_index=True)
        temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            result[HISTORY_COLUMNS].to_csv(temp, index=False, encoding='utf-8-sig')
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    return row

def get_monitoring(history_path=None):
    return monitoring(read_history(history_path or ROOT / 'data/operational_history.csv'))
