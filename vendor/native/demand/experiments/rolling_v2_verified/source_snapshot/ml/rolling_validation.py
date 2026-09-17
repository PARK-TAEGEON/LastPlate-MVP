"""Retrospective rolling experiments; never promotes or synthesizes acquisition timestamps."""
import argparse
import json
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
from .config import ROOT, MENU_RULES
from .prepare_data import read_csv,normalize
from .weather import merge_observed_weather
from .train import fit_bundle,bundle_predict,period
from .evaluate import metrics
from .feature_engineering import features_for_bundle
from .model_registry import atomic_json
from .provenance import training_provenance,model_parameters

WEATHER_FEATURES=['temp_mean','temp_max','temp_min','humidity']

def simple_baselines(train,val):
    mean=float(train.actual_diners.mean())
    weekday=train.groupby('weekday').actual_diners.mean().to_dict()
    rate=float(train.actual_diners.sum()/train.available_population.sum())
    # Sequential one-day-ahead protocol: only earlier target dates' actuals.
    past=train.actual_diners.tolist()
    lag=[]
    for row in val.itertuples():
        lag.append(round(float(np.mean(past[-5:]))))
        past.append(row.actual_diners)
    return {'train_mean':np.repeat(round(mean),len(val)),
            'weekday_mean':np.rint(val.weekday.map(weekday).fillna(mean)).to_numpy(),
            'available_rate':np.rint(val.available_population*rate).to_numpy(),
            'past_5_actual_mean':np.asarray(lag)}

def rolling(root=ROOT,output=None):
    root=Path(root)
    out=Path(output or root/'experiments/rolling_v2')
    if out.exists():
        raise ValueError('Use a fresh experiment folder; existing results are immutable')
    out.mkdir(parents=True)
    for folder in ('ml','tools','adapters'):
        snapshot=out/'source_snapshot'/folder
        snapshot.mkdir(parents=True)
        for source in (root/folder).glob('*.py'):
            shutil.copyfile(source,snapshot/source.name)
    (out/'fit_metadata').mkdir()
    d=normalize(read_csv(root/'data/processed/lunch.csv'))
    w=read_csv(root/'experiments/weather/data/processed/weather_daily.csv')
    joined=merge_observed_weather(d,w)
    complete=joined[WEATHER_FEATURES].notna().all(axis=1)
    excluded=[]
    for row in joined.loc[~complete].itertuples():
        observation=row.date-pd.Timedelta(days=1)
        daily=w[pd.to_datetime(w.date)==observation]
        reason='previous_date_not_in_source' if daily.empty else ('incomplete_hourly_day' if int(daily.observed_hours.iloc[0])!=24 else 'missing_temperature_or_humidity')
        excluded.append(dict(date=str(row.date.date()),observed_date=str(observation.date()),reason=reason))
    pd.DataFrame(excluded).to_csv(out/'excluded_rows.csv',index=False)
    joined.assign(included=complete).to_csv(out/'joined_audit.csv',index=False)
    result_rows=[];prediction_rows=[];gains=[];permutations=[];folds=[]
    for fold,start in enumerate((600,750,900,1050),1):
        stop=min(start+150,len(d)) if fold<4 else len(d)
        val_start=d.date.iloc[start];val_end=d.date.iloc[stop-1]
        train=joined.loc[(joined.date<val_start)&complete].copy()
        val=joined.loc[joined.date.between(val_start,val_end)&complete].copy()
        folds.append(dict(fold=fold,train=period(train),validation=period(val)))
        for name,pred in simple_baselines(train,val).items():
            result_rows.append(dict(fold=fold,model=name,group='baseline',rules='n/a',include_overtime=False,
                                    **metrics(val.actual_diners,pred),train_mae=None,mae_gap=None))
            prediction_rows.extend(dict(fold=fold,model=name,group='baseline',rules='n/a',include_overtime=False,
                                        date=str(date.date()),actual=float(y),predicted=int(p))
                                   for date,y,p in zip(val.date,val.actual_diners,pred))
        for include_ot in (True,False):
            for family in ('lightgbm','xgboost'):
                for group in 'ABCD':
                    for rules in (('v1','v2') if group in 'CD' else ('v2',)):
                        bundle=fit_bundle(train,family,group,WEATHER_FEATURES,rules,include_ot)
                        atomic_json(out/'fit_metadata'/f'{fold}-{family}-{group}-{rules}-ot{int(include_ot)}.json',
                                    dict(bundle['provenance'],features=bundle['features'],model_type=family,group=group,
                                         include_overtime=include_ot,parameters=model_parameters(bundle['model']),
                                         weather_contract='previous_day_observed' if group=='D' else 'not_used',
                                         train_period=period(train),validation_period=period(val)))
                        pred=bundle_predict(bundle,val)
                        train_score=metrics(train.actual_diners,bundle_predict(bundle,train))
                        score=metrics(val.actual_diners,pred)
                        row=dict(fold=fold,model=family,group=group,rules=rules,include_overtime=include_ot,
                                 **score,train_mae=train_score['mae'],mae_gap=score['mae']-train_score['mae'])
                        result_rows.append(row)
                        prediction_rows.extend(dict(fold=fold,model=family,group=group,rules=rules,include_overtime=include_ot,
                                                    date=str(date.date()),actual=float(y),predicted=int(p))
                                               for date,y,p in zip(val.date,val.actual_diners,pred))
                        gain=bundle['model'].feature_importances_.astype(float)
                        gains.extend(dict(fold=fold,model=family,group=group,rules=rules,include_overtime=include_ot,
                                          feature=name,gain=float(value)) for name,value in zip(bundle['features'],gain))
                        if group=='D' and rules=='v2' and not include_ot:
                            # Held-out feature permutation, not causal identification.
                            x=features_for_bundle(bundle,val)
                            rng=np.random.default_rng(42+fold)
                            for feature in x:
                                deltas=[]
                                for repeat in range(3):
                                    shuffled=x.copy()
                                    shuffled[feature]=rng.permutation(shuffled[feature].to_numpy())
                                    pp=np.rint(np.maximum(0,bundle['model'].predict(shuffled)))
                                    deltas.append(metrics(val.actual_diners,pp)['mae']-score['mae'])
                                permutations.append(dict(fold=fold,model=family,group='D',rules='v2',include_overtime=False,
                                                         feature=feature,mae_increase_mean=float(np.mean(deltas)),
                                                         mae_increase_std=float(np.std(deltas)),repeats=3))
        print(f'fold {fold}: {len(train)} train / {len(val)} validation; completed',flush=True)
    pd.DataFrame(result_rows).to_csv(out/'metrics.csv',index=False)
    pred_frame=pd.DataFrame(prediction_rows)
    pred_frame.to_csv(out/'date_predictions.csv',index=False)
    pooled=[]
    for keys,g in pred_frame.groupby(['model','group','rules','include_overtime'],dropna=False):
        pooled.append(dict(zip(['model','group','rules','include_overtime'],keys))|metrics(g.actual,g.predicted))
    pooled=pd.DataFrame(pooled).sort_values('mae')
    pooled.to_csv(out/'pooled_metrics.csv',index=False)
    pd.DataFrame(gains).to_csv(out/'gain_importance.csv',index=False)
    pd.DataFrame(permutations).to_csv(out/'permutation_importance.csv',index=False)
    atomic_json(out/'manifest.json',dict(folds=folds,rows=len(d),common_rows=int(complete.sum()),
                excluded_rows=len(excluded),model_fits=96,baseline_evaluations=16,
                provenance=training_provenance(d,'v1_and_v2'),weather_features=WEATHER_FEATURES,
                weather_contract='previous_day_observed',acquisition_timestamps='not supplied; never generated',
                caveats=['Retrospective reuse of previously viewed historical periods, not a fresh test',
                         'Past-5 baseline assumes earlier days actuals are available; historical acquisition times unverified',
                         'No model promotion; no final full-data model fitted in this experiment']))
    print(pooled.to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--output',type=Path)
    a=p.parse_args();rolling(a.root,a.output)
