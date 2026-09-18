"""Reuse lastplate-db 0.3.0. SQL outside that module is integration metadata only."""
import json, hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from lastplate_db import (Repository, persist_demand_result, persist_operation_result,
    persist_actual_result, get_dashboard_kpis, get_dashboard_readiness,
    get_learning_dataset, get_training_dataset)


def now():
    return datetime.now(timezone.utc).isoformat()


class Conflict(ValueError):
    pass


class Persistence:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.repo = Repository(path)
        self.repo.connection.executescript('''
            CREATE TABLE IF NOT EXISTS api_runs (
                request_id TEXT PRIMARY KEY, site_id TEXT NOT NULL, target_date TEXT NOT NULL,
                request_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS api_acknowledgements (
                request_id TEXT PRIMARY KEY REFERENCES api_runs(request_id),
                acknowledged_at TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind='read_only'));
            CREATE TABLE IF NOT EXISTS api_actual_links (
                result_id TEXT PRIMARY KEY REFERENCES actual_results(result_id),
                request_id TEXT NOT NULL REFERENCES api_runs(request_id));
            CREATE TABLE IF NOT EXISTS api_site_settings (
                site_id TEXT PRIMARY KEY, settings_json TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS api_plan_confirmations (
                request_id TEXT PRIMARY KEY REFERENCES api_runs(request_id),
                day_revision INTEGER NOT NULL, diners INTEGER NOT NULL,
                servings INTEGER NOT NULL, confirmed_at TEXT NOT NULL, is_demo INTEGER NOT NULL);
        ''')

    def close(self):
        self.repo.close()

    def ensure_site(self, request):
        with self.repo.transaction():
            existing = self.repo.get_site(request.site_id)
            if existing:
                if bool(existing['is_demo']) != request.is_demo:
                    raise Conflict('DEMO 사업장과 실제 사업장은 서로 다른 site_id를 사용하세요.')
                return existing
            return self.repo.create_site(site_id=request.site_id, site_name=request.site_name,
                registered_population=request.attendance.registered_population,
                meal_capacity=request.meal_capacity, source_type='DEMO' if request.is_demo else 'MANUAL',
                is_demo=request.is_demo, record_status='UNVALIDATED')

    def demand(self, request, result, request_id):
        self.ensure_site(request)
        raw = result['source_payload']
        version = 'lastplate-public-input/1.0'
        with self.repo.transaction():
            if not self.repo.get_feature_schema(version):
                self.repo.register_feature_schema(version, {
                    'employees':'number','vacation':'number','business_trip':'number',
                    'work_from_home':'number','overtime':'number','date':'string','menu':'string',
                    'request':'object','warnings':'array'})
        # observed_at uses the model's recorded input timestamp, not an HR acquisition receipt.
        snapshot = {**raw['input_data'], 'request':request.model_dump(mode='json'),
                    'warnings':result['warnings'], 'demand_source_payload':raw,
                    'registered_population':request.attendance.registered_population,
                    'available_population':result['available_population']}
        return persist_demand_result(self.repo, request.site_id, {
            **result, 'request_id':request_id, 'input_snapshot':snapshot,
            'source_type':'MODEL','is_demo':request.is_demo,'record_status':'UNVALIDATED',
            'created_at':raw['created_at'], 'feature_schema_version':version,
            'observed_at':raw['created_at'], 'source_lineage_id':'api-request:'+request_id})

    def operation(self, request, prediction_id, result):
        return persist_operation_result(self.repo, request.site_id, prediction_id, {
            **result,'target_date':str(request.target_date),'source_type':'DEMO' if request.is_demo else 'AGENT',
            'is_demo':request.is_demo,'record_status':'UNVALIDATED'})

    def decision(self, request, prediction_id, operation_id, result):
        return self.repo.save_decision(site_id=request.site_id,target_date=str(request.target_date),
            decision_type=result['decision_type'], recommendation_json={
                'prediction_id':prediction_id,'operation_plan_id':operation_id,'result':result},
            critical_alerts_json=result['critical_alerts'],confidence=result['confidence'],
            requires_human_approval=True,approved=False,
            source_type='DEMO' if request.is_demo else 'AGENT',is_demo=request.is_demo,record_status='UNVALIDATED')

    def save_run(self, request, result):
        with self.repo.transaction():
            self.repo.connection.execute('INSERT INTO api_runs VALUES (?,?,?,?,?,?)', (
                result['request_id'],request.site_id,str(request.target_date),
                json.dumps(request.model_dump(mode='json'),ensure_ascii=False,allow_nan=False),
                json.dumps(result,ensure_ascii=False,allow_nan=False),now()))

    def get_run(self, request_id):
        row=self.repo.connection.execute('SELECT * FROM api_runs WHERE request_id=?',(request_id,)).fetchone()
        return None if row is None else {**dict(row),'request':json.loads(row['request_json']),
                                        'result':json.loads(row['result_json'])}

    def actual_data(self, request):
        site=self.repo.get_site(request.site_id)
        if not site:
            raise Conflict('사업장을 찾지 못했습니다. 운영 계획을 먼저 생성하세요.')
        if request.is_demo is not None and bool(site['is_demo']) != request.is_demo:
            raise Conflict('운영 결과의 DEMO 구분이 사업장과 다릅니다.')
        data=request.model_dump(mode='json',exclude={'plan_request_id','reason','expected_revision'})
        data['is_demo']=bool(site['is_demo'])
        data['notes']=data['notes'] or None
        data.update(source_type='DEMO' if data['is_demo'] else 'MANUAL',record_status='UNVALIDATED')
        if request.plan_request_id:
            run=self.get_run(request.plan_request_id)
            if not run or (run['site_id'],run['target_date'])!=(request.site_id,str(request.target_date)):
                raise Conflict('선택한 계획이 사업장·운영일과 다릅니다. 계획을 다시 선택하세요.')
            if run['result']['persistence_status']!='SUCCESS':
                raise Conflict('연결할 계획의 저장을 먼저 완료하세요.')
        return data

    def actual(self, request):
        data=self.actual_data(request)
        # A repeated identical submission is safe. Corrections need the existing audit workflow.
        with self.repo.transaction():
            existing=self.repo.get_actual_result(request.site_id,str(request.target_date))
            if existing:
                if any(existing.get(k)!=v for k,v in data.items()):
                    raise Conflict('이 날짜의 운영 결과가 이미 있습니다. 저장된 기록의 ‘정정하기’를 이용하세요.')
                link=self.repo.connection.execute('SELECT request_id FROM api_actual_links WHERE result_id=?',(existing['result_id'],)).fetchone()
                if request.plan_request_id and link and link[0]!=request.plan_request_id:
                    raise Conflict('다른 계획 버전에 연결된 결과가 있습니다. 저장된 기록을 확인하세요.')
                return existing
            persist_actual_result(self.repo,request.site_id,data)
            row=self.repo.get_actual_result(request.site_id,str(request.target_date))
            if request.plan_request_id:
                self.repo.connection.execute('INSERT INTO api_actual_links VALUES (?,?)',(row['result_id'],request.plan_request_id))
            return row

    @staticmethod
    def actual_revision(row):
        return hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def correct_actual(self, request):
        data=self.actual_data(request)
        with self.repo.transaction():
            current=self.repo.get_actual_result(request.site_id,str(request.target_date))
            if not current:raise Conflict('정정할 기록을 찾지 못했습니다.')
            if self.actual_revision(current)!=request.expected_revision:
                raise Conflict('다른 작업에서 기록이 변경됐습니다. 기록을 다시 불러온 뒤 정정하세요.')
            link=self.repo.connection.execute('SELECT request_id FROM api_actual_links WHERE result_id=?',(current['result_id'],)).fetchone()
            if request.plan_request_id and link and link[0]!=request.plan_request_id:
                raise Conflict('정정으로 연결 계획을 바꿀 수 없습니다. 원래 연결 계획을 사용하세요.')
            changes={k:v for k,v in data.items() if k not in ('site_id','target_date') and current.get(k)!=v}
            if not changes:raise Conflict('변경한 값이 없습니다.')
            return self.repo.update_actual_result(request.site_id,str(request.target_date),changes,
                actor='LOCAL_OPERATOR',correction_source='MANUAL',reason=request.reason)

    def history(self, site_id, limit=30):
        # Select the last prediction made BEFORE actual entry. Later replans cannot rewrite error history.
        rows=self.repo._many('''SELECT a.*,p.prediction_id,p.predicted_diners,
            o.recommended_servings FROM actual_results a
            LEFT JOIN predictions p ON p.rowid=(SELECT q.rowid FROM predictions q
                WHERE q.site_id=a.site_id AND q.target_date=a.target_date AND q.created_at<a.created_at
                ORDER BY q.created_at DESC,q.rowid DESC LIMIT 1)
            LEFT JOIN operation_plans o ON o.rowid=(SELECT z.rowid FROM operation_plans z
                WHERE z.prediction_id=p.prediction_id AND z.created_at<a.created_at
                ORDER BY z.created_at DESC,z.rowid DESC LIMIT 1)
            WHERE a.site_id=? ORDER BY a.target_date DESC LIMIT ?''',(site_id,limit))
        for row in rows:
            link=self.repo.connection.execute('SELECT request_id FROM api_actual_links WHERE result_id=?',(row['result_id'],)).fetchone()
            run=self.get_run(link[0]) if link else None
            if not run:
                # Legacy records have no explicit link. Preserve the prediction selected above.
                candidates=self.repo.connection.execute('SELECT request_id,result_json FROM api_runs WHERE site_id=? AND target_date=? ORDER BY created_at DESC,rowid DESC',(site_id,row['target_date'])).fetchall()
                for candidate in candidates:
                    if json.loads(candidate['result_json']).get('persistence_ids',{}).get('prediction_id')==row['prediction_id']:
                        run=self.get_run(candidate['request_id']);break
            row['plan_request_id']=run['request_id'] if run else None
            row['operating_diners']=None
            row['confirmed_diners']=None;row['final_servings']=None
            if run:
                result=run['result']
                row['predicted_diners']=(result.get('demand') or {}).get('predicted_diners')
                row['operating_diners']=(result.get('operation') or {}).get('base_demand')
                row['recommended_servings']=(result.get('operation') or {}).get('recommended_servings')
                row['prediction_id']=result.get('persistence_ids',{}).get('prediction_id')
                confirmation=self.repo.connection.execute('SELECT diners,servings FROM api_plan_confirmations WHERE request_id=? AND confirmed_at<=?',
                    (run['request_id'],row['created_at'])).fetchone()
                if confirmation:row['confirmed_diners'],row['final_servings']=confirmation
            prediction=row['predicted_diners']
            row['prediction_error']=None if prediction is None else abs(prediction-row['actual_diners'])
            row['overprep_servings']=None if row['prepared_servings'] is None else max(0,row['prepared_servings']-row['actual_diners'])
            row['model_difference']=None if prediction is None else row['actual_diners']-prediction
            row['operating_difference']=None if row['operating_diners'] is None else row['actual_diners']-row['operating_diners']
        return rows

    def kpis(self, site_id):
        metrics=get_dashboard_kpis(self.repo,site_id)
        readiness=get_dashboard_readiness(self.repo,site_id)
        return {**metrics, 'status':'insufficient_data' if all(v is None for v in metrics.values()) else 'ok',
            'retraining_readiness':{**readiness,'matched_learning_records':len(get_learning_dataset(self.repo,site_id)),
                'automatic_retraining':False,'note':'DEMO 및 검증되지 않은 데이터는 학습 집계에서 제외됩니다.'}}

    def inventory(self, site_id, snapshot_date, rows, is_demo):
        site=self.repo.get_site(site_id)
        if not site or bool(site['is_demo']) != is_demo:
            raise Conflict('사업장 정보 또는 DEMO 구분을 확인하세요.')
        ids=[]
        with self.repo.transaction():
            for item in rows:
                record=self.repo.save_inventory_snapshot(site_id=site_id,snapshot_date=str(snapshot_date),
                    ingredient_name=item['ingredient'],quantity=item['current_stock'],unit=item['unit'],
                    expiry_date=item['expiry_date'],lot_id=item.get('lot_id'),
                    source_type='USER_UPLOAD',is_demo=is_demo,record_status='UNVALIDATED')
                ids.append(record['inventory_id'])
        return ids

    def acknowledge(self, request_id):
        if self.get_run(request_id) is None:
            raise KeyError(request_id)
        with self.repo.transaction():
            self.repo.connection.execute('INSERT OR IGNORE INTO api_acknowledgements VALUES (?,?,?)',
                                        (request_id,now(),'read_only'))
        acknowledged_at=self.repo.connection.execute('SELECT acknowledged_at FROM api_acknowledgements WHERE request_id=?',(request_id,)).fetchone()[0]
        return {'request_id':request_id,'acknowledged':True,'approved':False,'automatic_execution':False,'acknowledged_at':acknowledged_at,
                'message':'권고를 읽었음을 기록했습니다. 발주·메뉴 변경은 실행되지 않습니다.'}
