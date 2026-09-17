from dataclasses import replace
from datetime import datetime,time,timezone
import json
import pandas as pd
import pytest
from ml import time_contract as clock
from ml.time_contract import ServiceConfig
from ml.config import ROOT,STAFF
from ml.prepare_data import read_csv,normalize
from ml.model_registry import ModelRegistry
from ml.retrain import GatePolicy,batch_retrain,should_promote
from ml.retrain_journal import RetrainJournal
from tools.demand import predict_demand,record_actual_result
from test_service_v2 import dummy

@pytest.fixture
def batch(tmp_path,monkeypatch):
    config=ServiceConfig(tmp_path/'storage',tmp_path/'models','Asia/Seoul','10:00','14:00')
    data=normalize(read_csv(ROOT/'data/processed/lunch.csv'))
    base=tmp_path/'base.csv';data.head(100).to_csv(base,index=False)
    registry=ModelRegistry(config.model_dir)
    original=registry.promote(dummy(value=0),dict(trained_through=str(data.iloc[99].date.date())))
    current=[datetime.now(timezone.utc)]
    monkeypatch.setattr(clock,'utc_now',lambda:current[0])
    for i,row in data.iloc[100:115].iterrows():
        target=str(row.date.date())
        current[0]=config.local_instant(row.date.date(),'09:00')
        inputs={c:float(row[c]) for c in STAFF};inputs.update(date=target,menu=row.menu)
        availability={c:dict(available_at=config.local_instant(row.date.date(),'08:00').isoformat(),source='isolated_clock_fixture') for c in STAFF}
        p=predict_demand(inputs,config=config,request_id='p'+str(i),availability=availability)
        current[0]=config.local_instant(row.date.date(),'15:00')
        record_actual_result(p['prediction_id'],int(row.actual_diners),config=config,request_id='a'+str(i),
                             measured_at=config.local_instant(row.date.date(),'14:00').isoformat(),actor='test_fixture')
    policy=GatePolicy(min_new=15,evaluation_rows=10,min_new_training_rows=5,min_absolute_improvement=5,min_relative_improvement=.02)
    seen=[]
    def fit(d,*args,**kwargs):
        seen.append(d.copy())
        return dummy(value=900)
    monkeypatch.setattr('ml.retrain.fit_bundle',fit)
    return config,base,tmp_path/'reports',policy,registry,original,seen

def execute(batch):
    c,base,out,policy,*_=batch
    return batch_retrain(config=c,base_path=base,report_dir=out,policy=policy)

def test_gate_promotion_and_no_reuse(batch):
    result=execute(batch)
    assert result['status']=='promoted'
    c,base,out,policy,r,old,seen=batch
    assert seen[0].date.max()<pd.Timestamp(result['gate_period']['start'])
    assert len(seen)==2
    assert (r.path/'archive'/old['model_version']).exists()
    assert execute(batch)['status']=='insufficient_new_data'

def test_rejection_keeps_incumbent(batch,monkeypatch):
    monkeypatch.setattr('ml.retrain.fit_bundle',lambda *a,**k:dummy(value=100000))
    result=execute(batch)
    assert result['status']=='kept_incumbent'
    assert batch[4].current_version()==batch[5]['model_version']
    assert execute(batch)['status']=='insufficient_new_data'

@pytest.mark.parametrize('stage,expected',[('after_reserve','interrupted'),('after_evaluation','interrupted'),
    ('after_artifact','committed'),('before_pointer','committed'),('after_pointer','committed'),('before_report','committed')])
def test_crash_recovery_and_burned_gate(batch,monkeypatch,stage,expected):
    def fail(at):
        if at==stage:raise RuntimeError('injected process failure')
    monkeypatch.setattr('ml.retrain.failure_point',fail)
    with pytest.raises(RuntimeError,match='injected'):
        execute(batch)
    c,base,out,policy,r,old,seen=batch
    journal=RetrainJournal(c.model_dir)
    consumed=journal.used_dates()
    assert len(consumed)==10
    runs=journal.recover(r,out)
    assert runs[-1]['state']==expected
    version=r.current_version()
    journal.recover(r,out)
    assert r.current_version()==version and journal.used_dates()==consumed
    assert (out/(runs[-1]['id']+'.json')).exists()
    monkeypatch.setattr('ml.retrain.failure_point',lambda _:None)
    assert execute(batch)['status']=='insufficient_new_data'

def test_report_io_failure_recovers_without_second_promotion(batch):
    batch[2].write_text('blocked output path')
    with pytest.raises(FileExistsError):execute(batch)
    journal=RetrainJournal(batch[0].model_dir)
    assert journal.runs()[-1]['state']=='committed'
    version=batch[4].current_version()
    batch[2].unlink()
    journal.recover(batch[4],batch[2])
    assert batch[4].current_version()==version

def test_demo_store_cannot_retrain_production(batch):
    with pytest.raises(ValueError,match='replay/demo'):
        batch_retrain(config=replace(batch[0],mode='demo'),base_path=batch[1],report_dir=batch[2])

def test_default_gate_minimum_and_small_improvement():
    p=GatePolicy()
    assert p.evaluation_rows==30 and p.min_absolute_improvement==5 and p.min_relative_improvement==.02
    assert not should_promote(90,89)
    assert not should_promote(90,85)
    assert should_promote(90,84.9)
    with pytest.raises(ValueError):GatePolicy(evaluation_rows=1)

def test_sqlite_transaction_rolls_back_actual_on_audit_failure(service):
    # Fixture is supplied by test_service_v2 through conftest import.
    from ml.service_store import ServiceStore
    from ml.errors import StorageError
    from test_service_v2 import predict,actual
    p=predict(service)
    with ServiceStore(service[0]).connection(write=True) as db:
        db.execute("CREATE TRIGGER reject_audit BEFORE INSERT ON actual_events BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(StorageError):actual(service,p)
    with ServiceStore(service[0]).connection() as db:
        assert db.execute('SELECT count(*) FROM actuals').fetchone()[0]==0
    with ServiceStore(service[0]).connection(write=True) as db:db.execute('DROP TRIGGER reject_audit')
    assert actual(service,p)['revision']==1
