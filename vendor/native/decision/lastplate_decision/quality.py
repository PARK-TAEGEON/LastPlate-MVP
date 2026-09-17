"""Quality warnings are distinct from ordinary provenance descriptions."""
import re

SOURCE = re.compile(r'^\s*(DEMO|SIMULATION|UNKNOWN|REAL)(?=$|[\s:;/_-])', re.I)
NOTE_TAG = re.compile(r'\b(DEMO|SIMULATION|UNKNOWN)\b', re.I)


def normalize_source(value):
    text=str(value).strip() if value is not None else ''
    match=SOURCE.match(text)
    return match.group(1).upper() if match else 'UNKNOWN' if not text else 'INFO'


def collect_quality(value, path='input'):
    records=[]
    def add(kind,message,where,warning=True):
        records.append(dict(kind=kind,message=message,path=where,warning=warning,affects_confidence=warning))
    def visit(obj,where):
        if isinstance(obj,dict):
            for field in ('data_sources','data_source','source_type'):
                if field not in obj:continue
                entries=obj[field] if isinstance(obj[field],dict) else dict(enumerate(obj[field])) if isinstance(obj[field],list) else {'':obj[field]}
                for name,text in entries.items():
                    kind=normalize_source(text)
                    add(kind,f'{kind} 출처: {text}',where+'.'+field+('.'+str(name) if name else ''),kind in {'DEMO','SIMULATION','UNKNOWN'})
            if obj.get('is_demo') is True:add('DEMO','DEMO 합성 데이터',where+'.is_demo')
            if where=='input.demand_result' and str(obj.get('mode','')).strip().lower() in {'demo','replay'}:
                add('DEMO','Demand '+str(obj['mode'])+' 모드: 운영 근거로 사용 불가',where+'.mode')
            for field in ('data_quality_notes','limitations','adapter_notes','provenance_notes'):
                for note in obj.get(field,[]):
                    # Compatibility with the exact informational message emitted by v0.1.1.
                    normal_ml=(str(note).startswith('ML v2: mode=operation, operational_eligible=True, availability_status=validated_declared_receipts'))
                    warning=field!='provenance_notes' and not normal_ml
                    match=NOTE_TAG.search(str(note)) if warning else None
                    kind=match.group(1).upper() if match else ('LIMITATION' if field=='limitations' else 'WARNING') if warning else 'INFO'
                    add(kind,str(note),where+'.'+field,warning)
            handled={'source_payload','decision_trace','upstream_traces','provenance','data_sources','data_source','source_type',
                     'data_quality_notes','limitations','adapter_notes','provenance_notes'}
            for key,item in obj.items():
                if key not in handled:visit(item,where+'.'+key)
        elif isinstance(obj,list):
            for i,item in enumerate(obj):visit(item,f'{where}[{i}]')
    visit(value,path)
    return records


def finalize_quality(records, excluded_prefixes=(), workflow_notes=()):
    records=[dict(r) for r in records]
    for record in records:
        if any(record['path']==p or record['path'].startswith(p+'.') or record['path'].startswith(p+'[') for p in excluded_prefixes):
            record['affects_confidence']=False
    for note in workflow_notes:
        if isinstance(note,dict):
            failed=note.get('kind')=='callback_failure'
            message=note.get('message',str(note))
            path='workflow.'+note.get('agent','unknown')
        else:
            message=str(note);failed='실패' in message;path='workflow'
        records.append(dict(kind='WORKFLOW_FAILURE' if failed else 'INFO',message=message,
                            path=path,warning=failed,affects_confidence=failed))
    return records


def quality_notes(records):
    return list(dict.fromkeys((r['path']+': '+r['message']+(' [비선택/무관 근거]' if not r['affects_confidence'] else ''))
        for r in records if r['warning']))


def confidence_assessment(status, selected, critical, records):
    """Confidence means readiness of the selected operational recommendation, not diagnosis certainty."""
    evidence=[]
    failed=sorted({constraint for a in selected for constraint in a.failed_constraints})
    if status=='blocked':
        evidence.append(dict(kind='hard_constraint_failure',message='현재 계획 Hard Constraint FAIL: '+', '.join(failed),constraints=failed))
    if status=='needs_confirmation':
        evidence.append(dict(kind='incomplete_evidence',message='현재 계획 검증 미완료 또는 미해결 재실행 요청'))
    selected_ids={a.action_id for a in selected}
    for alert in critical:
        relevant=(alert.get('action_id') in selected_ids if alert.get('type')=='constraint_violation'
                  else alert.get('scope_relation')!='unrelated')
        if relevant:
            evidence.append(dict(kind='current_plan_risk',message=f"현재 계획 {alert.get('type')} {alert.get('severity')}: {alert.get('message','위험 확인 필요')}",
                                 alert=alert))
    warnings=[r for r in records if r['warning'] and r['affects_confidence']]
    for r in warnings:
        evidence.append(dict(kind=r['kind'],message=r['message'],path=r['path']))
    low=status!='ok' or any(r['kind']=='WORKFLOW_FAILURE' for r in warnings)
    level='LOW' if low else 'MEDIUM' if evidence else 'HIGH'
    reasons=list(dict.fromkeys(e['message'] for e in evidence)) or ['현재 계획의 필수 근거·소비 의존성·Hard Constraint 검증 통과']
    return level,reasons,evidence
