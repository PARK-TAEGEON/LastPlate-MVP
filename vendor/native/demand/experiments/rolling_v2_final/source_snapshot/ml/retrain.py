"""Explicit administrative batch job. Durable ledger precedes every evaluation."""
import argparse
from dataclasses import dataclass,asdict
import json
from pathlib import Path
import uuid
import math
import pandas as pd
from filelock import FileLock
from . import time_contract as clock
from .time_contract import ServiceConfig,aware_timestamp
from .model_registry import ModelRegistry
from .retrain_journal import RetrainJournal
from .prepare_data import read_csv,normalize
from .train import fit_bundle,bundle_predict,period
from .evaluate import metrics
from .provenance import frame_hash
from .weather import merge_observed_weather
from .config import WEATHER
from tools.demand import history

@dataclass(frozen=True)
class GatePolicy:
    min_new:int=60
    evaluation_rows:int=30
    min_new_training_rows:int=10
    min_absolute_improvement:float=5.0
    min_relative_improvement:float=0.02

    def __post_init__(self):
        if any(type(v) is not int for v in (self.evaluation_rows,self.min_new_training_rows,self.min_new)) or self.evaluation_rows<10 or self.min_new_training_rows<1 or self.min_new<1:
            raise ValueError('Gate requires >=10 dates and a positive new-training-row count')
        if not math.isfinite(self.min_absolute_improvement) or self.min_absolute_improvement<0 or not 0<=self.min_relative_improvement<1:
            raise ValueError('Invalid improvement threshold')

def should_promote(old_mae,new_mae,min_improvement=5.,min_relative=0.02):
    if min_improvement<0 or not 0<=min_relative<1:
        raise ValueError('Invalid improvement threshold')
    return new_mae<old_mae-max(min_improvement,old_mae*min_relative)

def failure_point(stage):
    """No-op hook, monkeypatched only by isolated fault-injection tests."""

def batch_retrain(*,config,base_path,report_dir,weather_daily=None,policy=GatePolicy(),trigger='count'):
    if config.mode!='operation':
        raise ValueError('Batch production retraining never reads replay/demo stores')
    if trigger not in ('count','manual','weekly','monthly'):
        raise ValueError('Unknown trigger')
    for path in (base_path,report_dir):
        if not Path(path).is_absolute():
            raise ValueError('Explicit absolute data/report paths are required')
    registry=ModelRegistry(config.model_dir)
    with FileLock(str(config.model_dir/'.retrain.lock')):
        journal=RetrainJournal(config.model_dir)
        recovered=journal.recover(registry,report_dir)
        now=clock.utc_now()
        if trigger in ('weekly','monthly') and recovered:
            latest=aware_timestamp(recovered[-1]['document']['started_at'])
            if (now-latest).total_seconds()<(7 if trigger=='weekly' else 30)*86400:
                return {'status':'not_due'}
        incumbent,meta=registry.load()
        rows=[]
        for prediction,actual in history(config):
            if prediction['mode']!='operation' or not prediction['operational_eligible']:
                continue
            if aware_timestamp(prediction['created_at'])>aware_timestamp(prediction['deadline_at']):
                raise ValueError('Late prediction detected in operation store')
            if aware_timestamp(actual['measured_at'])>now:
                raise ValueError('Future actual detected in operation store')
            row=dict(prediction['input_data'],actual_diners=actual['actual_diners'])
            rows.append(row)
        if not rows:
            return {'status':'insufficient_new_data','new_rows':0}
        ops=normalize(pd.DataFrame(rows),require_overtime=incumbent.get('include_overtime',True))
        cutoff=pd.Timestamp(meta['trained_through'])
        used=journal.used_dates()
        # Watermark excludes older corrected or newly imported labels as fresh gates.
        watermark=max(used) if used else str(cutoff.date())
        fresh=ops.loc[(ops.date>cutoff)&(ops.date>pd.Timestamp(watermark))]
        needed=policy.evaluation_rows+policy.min_new_training_rows
        if len(fresh)<needed or (trigger=='count' and len(fresh)<policy.min_new):
            return {'status':'insufficient_new_data','new_rows':len(fresh),'required':max(needed,policy.min_new if trigger=='count' else 0)}
        base=normalize(read_csv(base_path),require_overtime=incumbent.get('include_overtime',True))
        if (ops.date<=base.date.max()).any():
            raise ValueError('Operational dates overlap historical data; explicit reconciliation required')
        if incumbent['group']=='D':
            if weather_daily is None or not Path(weather_daily).is_absolute():
                raise ValueError('D requires an explicit historical daily weather path')
            base=merge_observed_weather(base,read_csv(weather_daily))
            features=incumbent.get('weather_features',WEATHER)
            base=base.loc[base[features].notna().all(axis=1)]
        all_data=normalize(pd.concat([base,ops],ignore_index=True),require_overtime=incumbent.get('include_overtime',True))
        gate=fresh.tail(policy.evaluation_rows)
        train=all_data.loc[all_data.date<gate.date.min()]
        if cutoff>=gate.date.min():
            raise ValueError('Incumbent has seen the proposed gate')
        run_id=uuid.uuid4().hex
        doc=dict(run_id=run_id,started_at=now.isoformat(),incumbent_version=meta['model_version'],
                 candidate_version='batch-'+run_id,gate_period=period(gate),candidate_train_period=period(train),
                 gate_dates=gate.date.dt.strftime('%Y-%m-%d').tolist(),gate_hash=frame_hash(gate),
                 training_data_hash=frame_hash(train),policy=asdict(policy),status='reserved')
        # Consume first, before fit/scoring or reports; crashes cannot free the dates.
        journal.reserve(run_id,doc['gate_dates'],doc)
        failure_point('after_reserve')
        options=dict(weather_features=incumbent.get('weather_features'),
                     rules_version=incumbent.get('feature_rules_version','v1'),
                     include_overtime=incumbent.get('include_overtime',True))
        candidate=fit_bundle(train,incumbent['kind'],incumbent['group'],**options)
        old_pred=bundle_predict(incumbent,gate);new_pred=bundle_predict(candidate,gate)
        old_score=metrics(gate.actual_diners,old_pred);new_score=metrics(gate.actual_diners,new_pred)
        accepted=should_promote(old_score['mae'],new_score['mae'],policy.min_absolute_improvement,policy.min_relative_improvement)
        doc.update(incumbent_metrics=old_score,candidate_metrics=new_score,accepted=accepted,
                   predictions=[dict(date=str(d.date()),actual=float(y),incumbent=int(o),candidate=int(n))
                                for d,y,o,n in zip(gate.date,gate.actual_diners,old_pred,new_pred)],status='evaluated')
        journal.update(run_id,'evaluated',doc)
        failure_point('after_evaluation')
        if accepted:
            full=fit_bundle(all_data,incumbent['kind'],incumbent['group'],**options)
            new_meta=dict(model_type=incumbent['kind'],train_period=period(all_data),trained_through=period(all_data)['end'],
                          validation_period=period(gate),validation_metrics=new_score,
                          weather_policy=meta.get('weather_policy','not_used'),
                          evaluation_note='Gate score is for the pre-refit challenger. Full-data refit needs separate operational validation.',
                          gate_run_id=run_id)
            registry.prepare_release(full,new_meta,version=doc['candidate_version'])
            failure_point('after_artifact')
            journal.update(run_id,'prepared',doc)
            failure_point('before_pointer')
            registry.activate(doc['candidate_version'],meta['model_version'])
            failure_point('after_pointer')
            state='committed';doc['status']='promoted'
        else:
            state='kept';doc['status']='kept_incumbent'
        journal.update(run_id,state,doc)
        failure_point('before_report')
        journal.export(dict(id=run_id,state=state,document=doc),report_dir)
        return doc

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--config',required=True,type=Path)
    p.add_argument('--base-path',required=True,type=Path)
    p.add_argument('--report-dir',required=True,type=Path)
    p.add_argument('--weather-daily',type=Path)
    p.add_argument('--trigger',choices=['count','manual','weekly','monthly'],default='count')
    p.add_argument('--recover-only',action='store_true')
    a=p.parse_args()
    raw=json.loads(a.config.read_text(encoding='utf-8'))
    policy=GatePolicy(**raw.pop('gate_policy',{}))
    config=ServiceConfig(**raw)
    if a.recover_only:
        with FileLock(str(config.model_dir/'.retrain.lock')):
            result=RetrainJournal(config.model_dir).recover(ModelRegistry(config.model_dir),a.report_dir)
    else:
        result=batch_retrain(config=config,base_path=a.base_path,report_dir=a.report_dir,weather_daily=a.weather_daily,policy=policy,trigger=a.trigger)
    print(json.dumps(result,ensure_ascii=False,indent=2))
