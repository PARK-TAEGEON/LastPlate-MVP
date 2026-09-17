"""Explicit batch command with a future-only challenger/incumbent gate."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from filelock import FileLock
from .config import ROOT
from .prepare_data import normalize, read_csv
from .model_registry import ModelRegistry, atomic_json
from .train import fit_bundle, bundle_predict, period, environment
from .evaluate import metrics
from tools.demand import read_history

def should_promote(old_mae, new_mae, min_improvement=0.0):
    if min_improvement < 0:
        raise ValueError('min_improvement must be nonnegative')
    return new_mae < old_mae - min_improvement

def operational_training_rows(history):
    rows = []
    for r in history.to_dict('records'):
        x = json.loads(r['input_json'])
        if x['date'] != r['date']:
            raise ValueError('History date and snapshot disagree')
        x['actual_diners'] = r['actual_diners']
        rows.append(x)
    return normalize(pd.DataFrame(rows)) if rows else pd.DataFrame()

def batch_retrain(root=ROOT, trigger='count', min_new=30, holdout_size=10, min_improvement=0.0, now=None):
    root = Path(root)
    if trigger not in ('count', 'weekly', 'monthly', 'manual'):
        raise ValueError('Unknown retraining trigger')
    if min_new < 1 or holdout_size < 5 or min_improvement < 0:
        raise ValueError('Invalid gate settings (holdout requires at least 5 dates)')
    now = now or datetime.now(timezone.utc)
    (root / 'models').mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / 'models/.retrain.lock')):
        registry = ModelRegistry(root / 'models')
        incumbent, meta = registry.load()
        state_path = root / 'models/retrain_state.json'
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        if trigger in ('weekly', 'monthly'):
            last = datetime.fromisoformat(state.get('last_attempt_at', meta['trained_at']))
            if (now-last).total_seconds() < (7 if trigger == 'weekly' else 30)*86400:
                return {'status': 'not_due', 'trigger': trigger}
        hpath = root / 'data/operational_history.csv'
        with FileLock(str(hpath) + '.lock'):
            history = read_history(hpath)
        ops = operational_training_rows(history)
        if ops.empty:
            return {'status': 'insufficient_new_data', 'new_rows': 0}
        cutoff = pd.Timestamp(meta['trained_through'])
        new = ops.loc[ops.date > cutoff].sort_values('date')
        since_attempt = new.loc[new.date > pd.Timestamp(state.get('last_considered_date', meta['trained_through']))]
        if trigger != 'manual' and len(since_attempt) < (min_new if trigger == 'count' else 1):
            return {'status': 'insufficient_new_data', 'new_rows': len(since_attempt)}
        if len(since_attempt) < holdout_size + 5:
            return {'status': 'insufficient_holdout', 'new_rows': len(since_attempt), 'required': holdout_size+5}
        base = normalize(read_csv(root / 'data/processed/lunch.csv'))
        if (ops.date <= base.date.max()).any():
            raise ValueError('Operational dates overlap original training history; reconcile explicitly')
        all_data = normalize(pd.concat([base, ops], ignore_index=True))
        # Even manual retries need a fresh gate: rejected holdout labels must not
        # be consulted repeatedly for subsequent promotion decisions.
        holdout = since_attempt.tail(holdout_size)
        candidate_train = all_data.loc[all_data.date < holdout.date.min()]
        if cutoff >= holdout.date.min():
            raise ValueError('Gate overlaps incumbent training dates')
        if incumbent['group'] == 'D':
            from .weather import merge_observed_weather
            from .config import WEATHER
            # Historical observations are lagged; operational weather comes only
            # from the prediction-time snapshot, not actual-time weather_json.
            original_weather = merge_observed_weather(base, read_csv(root / 'data/processed/weather_daily.csv'))
            selected = incumbent.get('weather_features', WEATHER)
            original_weather = original_weather.loc[original_weather[selected].notna().all(axis=1)]
            all_data = normalize(pd.concat([original_weather, ops], ignore_index=True))
            candidate_train = all_data.loc[all_data.date < holdout.date.min()]
        # Freeze family/features before looking at the gate, avoiding selection on it.
        fit_options = {'weather_features': incumbent['weather_features']} if 'weather_features' in incumbent else {}
        candidate = fit_bundle(candidate_train, incumbent['kind'], incumbent['group'], **fit_options)
        old_pred, new_pred = bundle_predict(incumbent, holdout), bundle_predict(candidate, holdout)
        old_score, new_score = metrics(holdout.actual_diners, old_pred), metrics(holdout.actual_diners, new_pred)
        accepted = should_promote(old_score['mae'], new_score['mae'], min_improvement)
        result = dict(status='promoted' if accepted else 'kept_incumbent',
                      incumbent_version=meta['model_version'], incumbent_metrics=old_score,
                      candidate_metrics=new_score, gate_period=period(holdout),
                      candidate_train_period=period(candidate_train), min_improvement=min_improvement,
                      evaluated_at=now.isoformat())
        if accepted:
            deployed = fit_bundle(all_data, incumbent['kind'], incumbent['group'], **fit_options)
            next_meta = dict(model_type=incumbent['kind'], train_period=period(all_data),
                             trained_through=period(all_data)['end'], mae=new_score['mae'],
                             validation_period=period(holdout), validation_metrics=new_score,
                             evaluation_note='Future-only gate before full refit; this exact deployment refit has no independent score.',
                             dependencies=environment(), model_parameters=deployed['model'].get_params(),
                             weather_policy=meta['weather_policy'], promotion=result.copy())
            next_meta['weather_features'] = incumbent.get('weather_features', [])
            saved = registry.promote(deployed, next_meta, expected_current=meta['model_version'])
            result['model_version'] = saved['model_version']
        run_id = now.strftime('%Y%m%dT%H%M%S%f')
        atomic_json(root / f'reports/retraining/{run_id}.json', result)
        pd.DataFrame(dict(date=holdout.date, actual=holdout.actual_diners,
                          incumbent_prediction=old_pred, candidate_prediction=new_pred)).to_csv(root / f'reports/retraining/{run_id}.csv', index=False)
        atomic_json(state_path, {'last_attempt_at': now.isoformat(), 'last_considered_date': str(new.date.max().date())})
        return result

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--trigger', choices=['count', 'weekly', 'monthly', 'manual'], default='count')
    p.add_argument('--min-new', type=int, default=30)
    p.add_argument('--holdout-size', type=int, default=10)
    p.add_argument('--min-improvement', type=float, default=0.0)
    a = p.parse_args()
    print(json.dumps(batch_retrain(a.root, a.trigger, a.min_new, a.holdout_size, a.min_improvement), ensure_ascii=False, indent=2))
