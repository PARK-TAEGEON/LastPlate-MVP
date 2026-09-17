"""Conservative observed-weather adapter. Never treats missing rainfall as zero."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .prepare_data import read_csv
from .config import ROOT, WEATHER

def combine_hourly(frames):
    """Collapse exact overlapping observations; never choose conflicting values."""
    if not frames:
        raise ValueError('At least one hourly source is required')
    combined = pd.concat(frames, ignore_index=True)
    keys = ['지점', '일시']
    unique = combined.drop_duplicates()
    if unique.duplicated(keys).any():
        raise ValueError('Conflicting observations for the same station-hour')
    return unique.sort_values(keys).reset_index(drop=True), len(combined)-len(unique)

def aggregate_hourly(raw, station=192):
    d = raw.loc[raw['지점'] == station].copy()
    if d.empty:
        raise ValueError('Requested station is absent')
    d['timestamp'] = pd.to_datetime(d['일시'], errors='raise')
    if d.timestamp.duplicated().any():
        raise ValueError('Duplicate station-hour observations')
    if not (d.timestamp == d.timestamp.dt.floor('h')).all():
        raise ValueError('Hourly observations must be aligned to the hour')
    d['date'] = d.timestamp.dt.normalize()
    rows = []
    for date, g in d.groupby('date', sort=True):
        complete = len(g) == 24
        temp = g['기온(°C)']
        rain = g['강수량(mm)']
        humidity = g['습도(%)']
        rows.append(dict(date=date, station=station, observed_hours=len(g),
            temp_mean=temp.mean() if complete and temp.notna().all() else np.nan,
            temp_max=temp.max() if complete and temp.notna().all() else np.nan,
            temp_min=temp.min() if complete and temp.notna().all() else np.nan,
            precipitation=rain.sum() if complete and rain.notna().all() else np.nan,
            humidity=humidity.mean() if complete and humidity.notna().all() else np.nan,
            rain=1.0 if rain.gt(0).any() else (0.0 if complete and rain.notna().all() else np.nan)))
    return pd.DataFrame(rows)

def merge_observed_weather(lunch, daily, lag_days=1):
    """Use a prior *calendar* day's observations; lag 0 leaks after-lunch weather."""
    if not isinstance(lag_days, int) or lag_days < 1:
        raise ValueError('Observed daily weather requires lag_days >= 1')
    w = daily.copy()
    w['date'] = pd.to_datetime(w['date']) + pd.Timedelta(days=lag_days)
    if w.date.duplicated().any():
        raise ValueError('Choose one weather station before merging')
    return lunch.merge(w[['date'] + WEATHER], on='date', how='left', validate='one_to_one')

def main():
    p = argparse.ArgumentParser()
    inputs = p.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--source')
    inputs.add_argument('--sources', nargs='+')
    p.add_argument('--station', type=int, default=192)
    p.add_argument('--root', type=Path, default=ROOT)
    a = p.parse_args()
    sources = a.sources or [a.source]
    raw, duplicate_extra = combine_hourly([read_csv(source) for source in sources])
    daily = aggregate_hourly(raw, station=a.station)
    out = a.root / 'data/processed'
    out.mkdir(parents=True, exist_ok=True)
    daily.to_csv(out / 'weather_daily.csv', index=False, encoding='utf-8-sig')
    if len(sources) > 1:
        raw.to_csv(out / 'weather_hourly_combined.csv', index=False, encoding='utf-8-sig')
    lunch = read_csv(out / 'lunch.csv')
    dates = set(pd.to_datetime(lunch.date))
    info = dict(rows=len(raw), columns=list(raw), missing=raw.isna().sum().astype(int).to_dict(),
                sources=[str(s) for s in sources], duplicate_extra=duplicate_extra,
                station_records=raw[['지점', '지점명']].drop_duplicates().to_dict('records'),
                start=str(raw['일시'].min()), end=str(raw['일시'].max()), daily_rows=len(daily),
                same_day_overlap=len(dates & set(daily.date)),
                lag1_overlap=len(dates & set(daily.date + pd.Timedelta(days=1))),
                complete_feature_days=int(daily[WEATHER].notna().all(axis=1).sum()),
                caveat='Hourly extremes are not official daily extremes. Missing rainfall remains unknown. Prior-day observations only; forecasts require issue-time provenance.')
    (a.root / 'reports').mkdir(exist_ok=True)
    (a.root / 'reports/weather_profile.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(info, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
