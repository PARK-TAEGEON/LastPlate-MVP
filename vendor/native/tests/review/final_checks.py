import tempfile
import sys,json,copy,statistics
from pathlib import Path
BASE=Path(tempfile.mkdtemp(prefix='lastplate-review012-'));ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'reports/p1-v012/previous-invariants'
sys.path.insert(0,str(ROOT))
from integration import run_lastplate_pipeline,PipelineConfig
p=json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf-8'));p['supply_events']=[]
for lot in p['inventory']:lot.update(current_stock=1000000,unit='g',expiry_date='2026-10-01',minimum_stock=0,planned_order=0,last_used_date='2026-09-17')
for row in p['prices']:
    for k in ('current_price','price_1w_ago','price_2w_ago','price_3w_ago','price_4w_ago'):row[k]=1000
for row in p['monthly_prices']:row['average_price']=1000
cfg=PipelineConfig(storage_dir=BASE/'final-check-store-011')
q=copy.deepcopy(p);q['request_id']='public-superseded';q['event']={'event_type':'supply_risk','superseded':True,'ingredient':'두부','date':'2026-09-18','severity':'HIGH','description':'REVOKED_PUBLIC_SUPPLY'}
r=run_lastplate_pipeline(q,config=cfg)
(OUT/'public-superseded.json').write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print(json.dumps({'pipeline':r['pipeline_status'],'superseded_events':r['inventory_risk']['detected_events'],'supply_risks':r['inventory_risk']['supply_risks'],'decision_inventory_actions':r['decision']['inventory_actions']},ensure_ascii=False),flush=True)
