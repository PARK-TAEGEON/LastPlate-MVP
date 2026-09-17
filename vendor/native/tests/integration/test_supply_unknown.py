import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from integration import run_lastplate_pipeline,PipelineConfig

def test_undated_supply_is_preserved_and_not_a_pass(tmp_path):
    p=json.loads((ROOT/'examples/lh_like.json').read_text(encoding='utf8'))
    p['supply_events']=[dict(event_type='supply_risk',ingredient='두부',severity='HIGH',description='date missing',source_type='DEMO')]
    r=run_lastplate_pipeline(p,config=PipelineConfig(storage_dir=tmp_path))
    assert r['pipeline_status']=='COMPLETE',r['errors']
    assert any(e['event_type']=='supply_risk' and e['date'] is None for e in r['inventory_risk']['detected_events'])
    assert r['inventory_risk']['current_plan_checks']['supply']=='UNKNOWN'
    assert r['decision']['active_evidence_summary']['current_plan_checks']['supply']=='UNKNOWN'
