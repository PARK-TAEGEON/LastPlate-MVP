"""Read supplied files without executing or following embedded instructions."""
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from .config import ALIASES, STAFF, ROOT

def read_csv(path_or_bytes):
    raw = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    for encoding in ('utf-8-sig', 'cp949'):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError('Unsupported CSV encoding')

def load_lh(path):
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            members = [n for n in z.namelist() if n.rsplit('/', 1)[-1] == 'train.csv']
            if len(members) != 1:
                raise ValueError('ZIP must contain exactly one train.csv')
            return read_csv(z.read(members[0]))
    return read_csv(path)

def normalize(frame, require_target=True, require_overtime=True):
    d = frame.rename(columns=ALIASES).copy()
    if d.columns.duplicated().any():
        raise ValueError('Conflicting Korean/English field aliases')
    staff = STAFF if require_overtime else [c for c in STAFF if c != 'overtime']
    required = ['date', 'menu'] + staff + (['actual_diners'] if require_target else [])
    missing = set(required) - set(d.columns)
    if missing:
        raise ValueError(f'Missing fields: {sorted(missing)}')
    d['date'] = pd.to_datetime(d['date'], errors='raise')
    if d['date'].isna().any() or d['date'].dt.tz is not None:
        raise ValueError('Dates must be non-null local calendar dates')
    if not (d['date'] == d['date'].dt.normalize()).all():
        raise ValueError('Use a calendar date, not an intraday timestamp')
    if d['date'].duplicated().any():
        raise ValueError('Duplicate lunch dates: resolve explicitly before loading')
    day = d['date'].dt.dayofweek
    if 'weekday' in d:
        observed = d['weekday'].map({c: i for i, c in enumerate('월화수목금토일')})
        if observed.isna().any() or not (observed == day).all():
            raise ValueError('weekday conflicts with date (or is not 월/화/수/목/금/토/일)')
    d['weekday'] = day.map(dict(enumerate('월화수목금토일')))
    for col in staff + (['actual_diners'] if require_target else []):
        d[col] = pd.to_numeric(d[col], errors='raise').astype(float)
        if not np.isfinite(d[col]).all() or (d[col] < 0).any():
            raise ValueError(f'{col} must be finite and nonnegative')
    if (d['employees'] <= 0).any():
        raise ValueError('employees must be positive')
    if d['menu'].isna().any() or not d['menu'].map(lambda x: isinstance(x, str) and bool(x.strip())).all():
        raise ValueError('menu must be a nonempty string')
    d['available_population'] = d['employees'] - d[['vacation', 'business_trip', 'work_from_home']].sum(axis=1)
    if (d['available_population'] <= 0).any():
        raise ValueError('Estimated available population must be positive')
    if require_target:
        d['participation_rate'] = d['actual_diners'] / d['available_population']
    return d.sort_values('date').reset_index(drop=True)

def correct_source_weekdays(raw):
    """Explicit source cleanup; serving retains strict mismatch rejection."""
    fixed = raw.copy()
    expected = pd.to_datetime(raw['일자']).dt.dayofweek.map(dict(enumerate('월화수목금토일')))
    bad = raw['요일'] != expected
    corrections = [dict(date=raw.loc[i, '일자'], supplied=raw.loc[i, '요일'], corrected=expected.loc[i]) for i in raw.index[bad]]
    fixed['요일'] = expected
    return fixed, corrections

def profile(raw):
    fixed, corrections = correct_source_weekdays(raw)
    d = normalize(fixed)
    return {
        'rows': len(raw), 'columns': list(raw.columns),
        'dtypes': {c: str(t) for c, t in raw.dtypes.items()},
        'missing': raw.isna().sum().astype(int).to_dict(),
        'empty_strings': {c: int(raw[c].astype(str).str.strip().eq('').sum()) for c in raw},
        'date_min': str(d.date.min().date()), 'date_max': str(d.date.max().date()),
        'duplicate_dates': int(d.date.duplicated().sum()),
        'target': '중식계', 'has_lunch': '중식계' in raw, 'has_dinner': '석식계' in raw,
        'estimated_available_min': float(d.available_population.min()),
        'estimated_available_max': float(d.available_population.max()),
        'participation_above_one': int((d.participation_rate > 1).sum()),
        'zero_targets': int((d.actual_diners == 0).sum()),
        'weekday_corrections': corrections,
        'population_caveat': 'Absence categories may overlap. No person-level identifiers or definitions supplied; denominator is an estimate, not verified attendance.',
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', required=True)
    p.add_argument('--root', type=Path, default=ROOT)
    a = p.parse_args()
    raw = load_lh(a.source)
    (a.root / 'data/processed').mkdir(parents=True, exist_ok=True)
    (a.root / 'reports').mkdir(parents=True, exist_ok=True)
    fixed, _ = correct_source_weekdays(raw)
    normalize(fixed).to_csv(a.root / 'data/processed/lunch.csv', index=False, encoding='utf-8-sig')
    info = profile(raw)
    info['source_sha256'] = hashlib.sha256(Path(a.source).read_bytes()).hexdigest()
    (a.root / 'reports/data_profile.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(info, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
