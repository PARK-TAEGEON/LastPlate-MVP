import json
from dataclasses import asdict,replace
from pathlib import Path
from adapters.langgraph_adapter import build_prediction_graph
from ml.config import ROOT
from ml.service_store import ServiceStore

def test_real_langgraph_invocation_and_retry(service):
    config,inputs,availability,now=service
    graph=build_prediction_graph(config)
    state={'input_data':inputs,'availability':availability,'request_id':'graph-request'}
    first=graph.invoke(state);second=graph.invoke(state)
    assert first['result']==second['result'] and first['error'] is None

def test_streamlit_form_and_retry(service,tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    config,inputs,availability,now=service
    config=replace(config,mode='replay')
    raw=asdict(config);raw['storage_dir']=str(config.storage_dir);raw['model_dir']=str(config.model_dir)
    path=tmp_path/'config.json';path.write_text(json.dumps(raw),encoding='utf-8')
    monkeypatch.setenv('LASTPLATE_CONFIG',str(path))
    app=AppTest.from_file(str(ROOT/'examples/streamlit_app.py'),default_timeout=30).run()
    assert not app.exception
    app.text_area[0].set_value(json.dumps(inputs))
    app.button[1].click().run()
    assert not app.exception
    app.button[1].click().run()
    assert not app.exception
    with ServiceStore(config).connection() as db:
        assert db.execute('SELECT count(*) FROM predictions').fetchone()[0]==1
