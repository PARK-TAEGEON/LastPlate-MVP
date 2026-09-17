"""Allowlisted business views. Native traces and internal states never become UI copy."""
from datetime import date

CONSTRAINTS = {'shortage':'재료 부족','expiry':'유통기한','allergy':'알레르기',
    'nutrition':'영양 기준','restriction':'사용 제한','supply':'공급 안정성',
    'capacity':'급식 용량','minimum_protein':'단백질','calorie_range':'열량',
    'kcal_range':'열량','sodium_max':'나트륨','allergy_restriction':'알레르기 제한'}

def labels(values):
    return list(dict.fromkeys(CONSTRAINTS.get(v,'추가 운영 조건') for v in values))

def quantity(value, unit='g'):
    if value is None:return None
    return round(value/1000 if unit=='g' else value,6)

def source_label(value):
    value=(value or '').upper()
    return '직접 업로드' if 'USER_UPLOAD' in value else '시연 자료' if 'DEMO' in value or 'SIMULATION' in value else '사업장 등록 자료'

def event_view(context, target):
    rows=[]
    for event in context.get('events',[]):
        delta=event.get('attendance_delta')
        active=not event.get('superseded') and bool(event.get('date')) and event['date']<=target<=(event.get('end_date') or event['date'])
        kind=event.get('event_type')
        label=(f'방문·운영 인원 {delta:+d}명' if delta is not None else
            {'supply_risk':'공급 위험 확인','restriction_event':'식재료 사용 제한 확인',
             'ingredient_restriction':'식재료 사용 제한 확인'}.get(kind,'운영 변경사항 확인'))
        if event.get('ingredient'):label=event['ingredient']+' · '+label
        rows.append({'date':event.get('date'),'end_date':event.get('end_date'),
            'label':label,'active':active,'needs_review':bool(event.get('needs_clarification')),
            'status':'취소된 변경' if event.get('superseded') else '선택일에 반영' if active else '선택일 반영 대상 아님'})
    uncertain=any(e.get('needs_clarification') for e in context.get('events',[])) or any(
        d.get('errors') or d.get('unparsed_segments') or d.get('status') not in ('ok','success')
        for d in context.get('diagnostics',[]))
    return {'rows':rows,'attendance_delta':context.get('attendance_delta',0),
        'needs_review':uncertain,'message':'날짜 또는 내용을 더 구체적으로 입력하세요.' if uncertain else '해석한 날짜와 인원 변화를 확인하세요.'}

def plan_view(result, request, *, created_at=None, version=None, acknowledged_at=None, previous=None):
    demand=result.get('demand') or {};op=result.get('operation') or {}
    risk=result.get('inventory_risk') or {};decision=result.get('decision') or {}
    serving=decision.get('serving_action') or {}
    blocked=decision.get('decision_type')=='BLOCK'
    ood=demand.get('applicability')=='OUT_OF_DISTRIBUTION'
    complete=result['pipeline_status']=='SUCCESS'
    outcome=('문제 해결 전 사용 불가 · 조리량 미확정' if blocked else
        '일부 계산 미완료 · 조리량 미확정' if not complete else
        '추가 확인 필요 · 조리량 미확정')
    # Read acknowledgement is never promoted to approval, even if the native value is non-null.
    issues=[];seen=set()
    def add(key,title,action,level='주의',target=None):
        identity=(key,target)
        if identity in seen:return
        seen.add(identity);issues.append({'title':title,'action':action,'level':level,'target':target})
    failures=labels(serving.get('failed_constraints',[]));unknown=labels(serving.get('unknown_constraints',[]))
    if failures:add('failed','충족하지 못한 조건: '+', '.join(failures),'해당 문제를 해결하고 다시 계획을 계산하세요.','차단')
    if unknown:add('unknown','확인이 필요한 조건: '+', '.join(unknown),'기한·입고·검증 자료를 확인하세요.')
    if demand.get('operational_eligible') is False or (op.get('source') or {}).get('operational_eligible') is False:
        add('evidence','현재 자료만으로 운영에 사용할 수 없습니다','운영 인원과 입력 자료의 확인 근거가 필요합니다.')
    if op.get('capacity_excess',0)>0:add('capacity','급식 용량을 초과했습니다','수용 가능 인원과 조리 설비를 확인하세요.','차단')
    requirement={r['ingredient']:r for r in op.get('ingredient_requirements',[])}
    mapping={
      'STOCK_SHORTAGE':('shortage','재고 부족','필요량과 재고를 확인하고 추가 확보를 검토하세요.'),
      'ingredient_shortage':('shortage','재고 부족','필요량과 재고를 확인하고 추가 확보를 검토하세요.'),
      'low_stock':('low','최소 재고 미달','안전 재고와 입고 일정을 확인하세요.'),
      'expiry_risk':('expiry','유통기한 확인 필요','기한과 사용 가능 상태를 확인한 뒤 사용 순서를 정하세요.'),
      'expired_stock':('expiry','기한 경과 재고','사용 가능한 재고에서 제외하고 현장 상태를 확인하세요.'),
      'overstock':('overstock','과다 재고','향후 식단의 소진 가능량을 검토하세요.'),
      'long_unused_inventory':('unused','장기 미사용 재고','보관 상태와 사용 계획을 확인하세요.'),
      'price_risk':('price','가격 변동 주의','가격 추이와 구매 영향을 확인하세요.'),
      'supply_risk':('supply','공급 위험','공급처와 입고 가능일을 확인하세요.'),
      'UNDER_ORDER':('order','예정 발주 부족','추가 확보량과 예정 발주를 비교하세요.'),
      'insufficient_order':('order','예정 발주 부족','추가 확보량과 예정 발주를 비교하세요.'),
      'OVER_ORDER':('overorder','예정 발주 과다','예정 발주량과 보관 가능량을 검토하세요.'),
      'MISSING_PLANNED_ORDER':('missing_order','예정 발주 미입력','예정 발주가 있으면 입력하세요. 입력이 없어 발주량 검수는 하지 않았습니다.'),
    }
    ignored={'DEMAND_NOT_APPLICABLE','DEMAND_EVIDENCE_UNKNOWN','LEGACY_ROUNDING_POLICY','constraint_violation'}
    for a in [*op.get('alerts',[]),*risk.get('alerts',[]),*decision.get('critical_alerts',[])]:
        if not isinstance(a,dict) or a.get('candidate_id'):continue
        kind=a.get('type') or a.get('code');target=a.get('ingredient')
        if kind in ignored:continue
        key,title,action=mapping.get(kind,(kind,'추가 검토 항목','입력 자료와 운영 조건을 확인한 뒤 다시 계산하세요.'))
        if key=='order' and target in requirement and not request.get('planned_orders'):continue
        if key=='shortage' and target in requirement:
            amount=quantity(requirement[target].get('purchase_need'),requirement[target].get('unit'))
            if amount is not None:action=f'계산상 {amount:g}kg 추가 확보가 필요합니다. 입고·기한을 확인하세요.'
        add(key,f'{target} · {title}' if target else title,action,'참고' if key in ('overstock','unused') else '주의',target)
    calculation_actions=[]
    for error in result.get('errors',[]):
        stage=error.get('stage');code=error.get('code')
        label={'demand':'예상 식수','operation':'조리량·식재료','inventory_risk':'재고·공급 위험','decision':'최종 운영 권고','events':'변경 사유 해석'}.get(stage,'운영 계획')
        action=('계산 시간이 초과됐습니다. 해당 날짜의 ‘계산 다시 시도’를 눌러 주세요.' if code=='STAGE_TIMEOUT' else
            '계산에 필요한 실행 패키지가 없습니다. README의 설치 명령으로 requirements.txt를 설치한 뒤 서버를 재시작하세요.' if code in ('ModuleNotFoundError','ImportError') else
            '계산 라이브러리를 불러오지 못했습니다. 서버 터미널에서 실행 환경을 점검한 뒤 다시 시도하세요.' if code=='OSError' else
            '모델 또는 계산 자료 파일을 찾지 못했습니다. 저장소 전체를 내려받았는지 확인하세요.' if code=='FileNotFoundError' else
            '일부 메뉴의 레시피 기준량이 없습니다. 등록된 메뉴로 수정한 뒤 다시 계산하세요.' if code=='RECIPE_MISSING' else
            '식재료 재고 자료를 확인한 뒤 다시 계산하세요.' if code=='INVENTORY_DATA_MISSING' else
            '식재료 수량 단위를 g 또는 kg로 확인한 뒤 다시 계산하세요.' if code=='UNIT_ERROR' else
            '이벤트 또는 위험 정보에 확인이 필요합니다. 입력을 확인하고 다시 계산하세요.' if code=='DECISION_NEEDS_CONFIRMATION' else
            '계산 다시 시도를 눌러 주세요. 반복되면 서버 실행 환경과 입력 자료를 확인해야 합니다.')
        add('calculation',label+' 계산을 완료하지 못했습니다',action,target=label)
        if action not in calculation_actions:calculation_actions.append(action)
    if result['persistence_status']!='SUCCESS':add('save','계산 결과가 완전히 저장되지 않았습니다','아래 ‘저장 다시 시도’를 누르세요. 계산 결과는 이 화면에 남아 있습니다.')
    risk_stock={r['ingredient']:r for r in risk.get('inventory_status',[])}
    orders={r['ingredient']:r for r in op.get('order_reviews',[])}
    entered_orders={r['ingredient']:r for r in request.get('planned_orders',[])}
    materials=[]
    for row in requirement.values():
        name=row['ingredient'];r=risk_stock.get(name,{});order=orders.get(name,{})
        entered=entered_orders.get(name)
        materials.append({'ingredient':name,'required_kg':quantity(row.get('cooking_required'),row.get('unit')),
            'stock_kg':quantity(row.get('stock'),row.get('unit')),
            'usable_kg':quantity(r.get('usable_today_g')),
            'additional_kg':quantity(row.get('purchase_need'),row.get('unit')),
            'planned_kg':quantity(order.get('planned_order'),order.get('unit')) if entered else None,
            'arrival_date':entered.get('arrival_date') if entered else None,
            'order_review':'미입력 · 확인 필요' if not entered else {'OK':'계산 범위 내','UNDER':'부족 검토','OVER':'과다 검토'}.get(order.get('status'),'검토 필요'),
            'arrival':'입고 확인됨' if r.get('order_arrival_verified') else '입고 확인 필요'})
    checks=[]
    for c in op.get('constraints',{}).get('checks',[]):
        key=c.get('constraint')
        checks.append({'label':CONSTRAINTS.get(key,'운영 조건'),'status':{'PASS':'기준 충족','FAIL':'기준 미달'}.get(c.get('status'),'확인 필요'),
            'actual':c.get('actual'),'minimum':c.get('minimum'),'maximum':c.get('maximum'),
            'unit':{'minimum_protein':'g','calorie_range':'kcal','sodium_max':'mg'}.get(key,''),
            'matched':c.get('matched',[])})
    candidates=[]
    evaluations={r.get('candidate_id'):r for r in decision.get('candidate_evaluations',[])}
    for c in risk.get('substitute_candidates',[]):
        evaluation=evaluations.get(c.get('candidate_id'),{})
        eligible=bool(c.get('eligible_for_review')) and evaluation.get('decision') not in ('BLOCK','NEEDS_CONFIRMATION')
        reasons=[]
        if c.get('nutrition_check')!='PASS':reasons.append('영양 기준 미달 또는 미확인')
        if c.get('inventory_available') is not True:reasons.append('재고 부족 또는 미확인')
        reasons+=['확인 필요: '+', '.join(labels(evaluation['unknown_constraints']))] if evaluation.get('unknown_constraints') else []
        if not eligible and not reasons:reasons.append('운영 조건 재검증 필요')
        candidates.append({'original_menu':c.get('original_menu'),'menu':c.get('candidate_menu'),
            'eligible':eligible,'status':'검토 가능 · 적용 전 재검증 필요' if eligible else '사용 불가',
            'nutrition':'충족' if c.get('nutrition_check')=='PASS' else '미달 또는 미확인',
            'inventory':'확보 가능' if c.get('inventory_available') is True else '부족 또는 미확인',
            'shortages':[{'ingredient':k,'kg':quantity(v)} for k,v in c.get('shortages_g',{}).items()],
            'cost':{'higher':'비용 증가','lower':'비용 감소','same':'비용 유사'}.get(c.get('price_effect'),'비용 미확인'),
            'reasons':reasons})
    changes=None
    if previous:
        old=previous.get('operation') or {}
        def diff(new,old):return None if new is None or old is None else new-old
        changes={'old_diners':old.get('base_demand'),'new_diners':op.get('base_demand'),
            'diners_delta':diff(op.get('base_demand'),old.get('base_demand')),
            'old_servings':old.get('recommended_servings'),'new_servings':op.get('recommended_servings'),
            'servings_delta':diff(op.get('recommended_servings'),old.get('recommended_servings')),
            'materials':[]}
        old_rows={r['ingredient']:r for r in old.get('ingredient_requirements',[])}
        for m in materials:
            prior=old_rows.get(m['ingredient'],{})
            delta=diff(m['required_kg'],quantity(prior.get('cooking_required'),prior.get('unit')))
            if delta:changes['materials'].append({'ingredient':m['ingredient'],'delta_kg':delta})
    return {'id':result['request_id'],'site_id':result['site_id'],'site_name':request['site_name'],
        'target_date':result['target_date'],'is_demo':result['is_demo'],'created_at':created_at,'version':version,
        'acknowledged_at':acknowledged_at,'saved':result['persistence_status']=='SUCCESS',
        'calculation':'계획 계산 완료' if complete else '일부 계산 미완료','calculation_complete':complete,
        'outcome':outcome,'blocked':blocked,'ood':ood,
        'next_action':(' '.join(calculation_actions) if calculation_actions else '해당 날짜의 계산 다시 시도를 눌러 주세요.') if not complete else
            (' · '.join(failures+unknown)+' 항목을 확인하고 다시 계산하세요.') if failures or unknown else '운영 인원과 재고, 입력 자료의 확인 근거가 필요합니다.',
        'model_diners':demand.get('predicted_diners'),'operating_diners':op.get('base_demand'),
        'review_servings':op.get('recommended_servings'),'final_servings':None,
        'margin_pct':op.get('safety_margin_pct'),'capacity':request['meal_capacity'],
        'menus':[m['menu_name'] for m in request['weekly_menu'] if m['date']==result['target_date'] and m['meal_type']=='lunch'],
        'issues':sorted(issues,key=lambda x:{'차단':0,'주의':1,'참고':2}[x['level']]),
        'materials':materials,'checks':checks,'candidates':candidates,'changes':changes,
        'affected_menus':[{'date':r.get('date'),'menu':r.get('menu_name'),'ingredient':r.get('ingredient') or r.get('affected_ingredient')} for r in risk.get('affected_menus',[])],
        'price_changes':[{'ingredient':r.get('ingredient'),'current':r.get('current_price'),'reference':r.get('reference_price'),'unit':r.get('unit'),'change_pct':r.get('price_change_pct')} for r in risk.get('price_risks',[]) if r.get('is_alert')],
        'supply_risks':[{'ingredient':r.get('ingredient'),'date':r.get('date'),'end_date':r.get('end_date')} for r in risk.get('supply_risks',[]) if not r.get('superseded')],
        'events':event_view(result.get('event_context',{}),result['target_date']),
        'event_inputs':[e for e in request.get('events',[]) if isinstance(e,str)],
        'sources':{'menu':source_label(request['sources'].get('weekly_menu')),
            'inventory':source_label(request['sources'].get('inventory')),'as_of':request['as_of']},
        'reason':'운영 기준 인원에 사업장 여유분을 더해 조리량을 계산했습니다. 재료 확보와 운영 조건을 확인해야 합니다.' if op.get('recommended_servings') is not None else '예상 식수와 조리량 계산을 완료한 뒤 조리 계획을 확인할 수 있습니다.'}

def actual_view(row, revision=None, corrections=None):
    keys=['site_id','target_date','actual_diners','prepared_servings','unserved_leftover_kg',
        'plate_waste_kg','ingredient_waste_kg','shortage','notes','created_at','updated_at',
        'is_demo','plan_request_id','predicted_diners','operating_diners','recommended_servings',
        'model_difference','operating_difference','overprep_servings']
    return {**{k:row.get(k) for k in keys},'revision':revision,
        'corrections':[{'reason':r.get('reason'),'created_at':r.get('corrected_at') or r.get('created_at')} for r in corrections or []]}
