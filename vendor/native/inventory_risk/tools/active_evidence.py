"""One native active-evidence projection shared by Risk and the integration boundary.

Audit/history is deliberately not consumed as current evidence. No operational action.
"""
from copy import deepcopy

COLLECTIONS=('detected_events','price_risks','supply_risks','alerts','affected_menus',
             'priority_use_candidates','substitute_candidates','nutrition_results','cost_impacts')

def active_events(events):
    return [e for e in events if not (e.get('superseded',False) if isinstance(e,dict) else e.superseded)]

def recheck_requests(report):
    events=active_events(report.get('detected_events',[]))
    pending=any(e.get('needs_clarification') for e in events)
    result=[]
    if any(e['event_type']=='attendance_event' for e in events) and not pending and not report.get('errors'):
        result.append('demand_forecast')
    if not pending and not report.get('errors') and any(report.get(k) for k in ('alerts','substitute_candidates','priority_use_candidates')):
        result.append('operation_agent')
    return result

def plan_checks(report):
    """Checks come from native FEFO allocation and actual executed observations."""
    checks={k:'UNKNOWN' for k in ('shortage','expiry','restriction','supply')}
    executed=set(report.get('execution',{}).get('executed_nodes',[]))
    audit=report.get('allocation_audit',[])
    if report.get('status')!='ok': return checks
    if 'inventory_analyzer' in executed and audit:
        checks['shortage']='FAIL' if any(x['shortage_g']>0 for x in audit) else 'PASS'
        checks['restriction']='FAIL' if any(x['restricted'] for x in audit) else 'PASS'
        # allocate() excludes expired lots at the service date; unresolved coverage is UNKNOWN.
        if checks['shortage']=='PASS': checks['expiry']='PASS'
    if 'supply_risk_analyzer' in executed and audit:
        required={x['ingredient'] for x in audit}
        risks=[r for r in report.get('supply_risks',[]) if r.get('ingredient') in required]
        unresolved=[e for e in active_events(report.get('detected_events',[])) if e.get('event_type')=='supply_risk'
                    and e.get('ingredient') in required and (not e.get('date') or e.get('needs_clarification'))]
        checks['supply']='UNKNOWN' if risks or unresolved else 'PASS'
    return checks

def project_active(report):
    """Drop superseded evidence and dependent records, including candidate-only edges.

    Mixed-cause records survive with only their active cause IDs. Never drop an
    unrelated risk or promote an incomplete/failed report to a successful one.
    """
    out=deepcopy(report)
    records=[x for key in COLLECTIONS for x in out.get(key,[]) if isinstance(x,dict)]
    history=out.get('audit',{}).get('supply_events',[])+(out.get('parsing_result') or {}).get('parsed_events',[])
    dead={x['event_id'] for x in records+history if x.get('superseded') and x.get('event_id')}
    dead_candidates=set()
    def obsolete(x):
        if not isinstance(x,dict): return False
        refs=set(x.get('cause_event_ids') or [])
        return bool(x.get('superseded') or x.get('event_id') in dead or x.get('cause_event_id') in dead
                    or (refs and refs<=dead) or x.get('candidate_id') in dead_candidates)
    for _ in range(len(records)+1):
        old=(len(dead),len(dead_candidates))
        for x in records:
            if obsolete(x):
                if x.get('event_id'): dead.add(x['event_id'])
        # A candidate with a surviving mixed-cause definition must not be removed by a cancelled ancillary result.
        for key in ('priority_use_candidates','substitute_candidates'):
            for x in out.get(key,[]):
                if obsolete(x) and x.get('candidate_id'): dead_candidates.add(x['candidate_id'])
        if old==(len(dead),len(dead_candidates)):break
    def clean(value):
        if isinstance(value,list):return [clean(x) for x in value if not obsolete(x)]
        if isinstance(value,dict):
            result={k:clean(v) for k,v in value.items() if k not in ('source_payload','audit','history')}
            if 'cause_event_ids' in result: result['cause_event_ids']=[x for x in result['cause_event_ids'] if x not in dead]
            return result
        return value
    for key in COLLECTIONS: out[key]=clean(out.get(key,[]))
    if 'risk_events' in out: out['risk_events']=clean(out['risk_events'])
    for key in ('constraints','checks','rechecks'):
        if key in out:out[key]=clean(out[key])
    out['affected_ingredients']=sorted({x.get('ingredient') or x.get('affected_ingredient') for key in ('alerts','affected_menus') for x in out[key] if x.get('ingredient') or x.get('affected_ingredient')})
    if out.get('parsing_result'):
        out['parsing_result']=clean(out['parsing_result'])
        out['parsing_result']['parsed_events']=active_events(out['parsing_result'].get('parsed_events',[]))
    # Derived gates and native coarse rechecks are rebuilt from the same active view.
    out['current_plan_checks']=plan_checks(out)
    extra=[x for x in clean(out.get('recommended_rechecks',[])) if not isinstance(x,str) or x not in ('operation_agent','operation','demand_forecast')]
    out['recommended_rechecks']=recheck_requests(out)+extra
    for name in ('operation_agent','demand_forecast'):
        previous=out.setdefault('recheck_status',{}).get(name,{})
        # Keep native parser/error blocking semantics. Supersession only removes stale requests.
        status=previous.get('status') if str(previous.get('status','')).startswith('blocked') and out.get('status')!='ok' else 'requested' if name in out['recommended_rechecks'] else 'not_requested'
        out['recheck_status'][name]={**previous,'status':status,'executed':False}
        if name=='demand_forecast':out['recheck_status'][name]['execute_allowed']=status=='requested'
    out['evidence_projection']={'superseded_event_ids':sorted(dead),'removed_candidate_ids':sorted(dead_candidates),'audit_excluded':True}
    return out
