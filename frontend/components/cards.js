export const $=id=>document.getElementById(id);
export const fmt=(value,empty='확인 필요')=>value==null?empty:typeof value==='number'?value.toLocaleString('ko-KR',{maximumFractionDigits:3}):String(value);
export const signed=value=>value==null?'비교 자료 없음':`${value>0?'+':''}${fmt(value)}`;
export const stamp=value=>value?new Date(value).toLocaleString('ko-KR',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'}):'저장 시각 확인 필요';
export function node(tag,content,className){const el=document.createElement(tag);if(content!=null)el.textContent=content;if(className)el.className=className;return el;}
export function text(id,value){$(id).textContent=value??'';}
export function metric(root,label,value){const row=node('div',null,'metric');row.append(node('span',label),node('strong',value));root.append(row);}
export function renderSectionState(id,section,label,retry){
  const root=$(id);root.replaceChildren();root.hidden=!['loading','error','empty'].includes(section.status);
  root.className='section-state'+(section.status==='error'?' error':'');root.setAttribute('role',section.status==='error'?'alert':'status');
  root.setAttribute('aria-busy',String(section.status==='loading'));
  if(root.hidden)return;
  root.append(node('span',section.status==='loading'?`${label} 불러오는 중…`:section.status==='empty'?`${label} 자료가 없습니다.`:`${label} ${section.retained?'갱신 실패 · 마지막으로 확인한 자료를 표시합니다.':'조회 실패.'} ${section.error}`));
  if(section.status==='error'&&retry){const button=node('button','다시 시도','secondary small');button.type='button';button.dataset.retry=retry;button.setAttribute('aria-label',`${label} 다시 시도`);root.append(button);}
}
export function table(root,columns,rows,caption){
  if(!rows.length){root.append(node('p','해당 자료가 없습니다.','muted'));return;}
  const wrapper=node('div',null,'table-scroll');wrapper.tabIndex=0;wrapper.setAttribute('role','region');wrapper.setAttribute('aria-label',caption||'자료 표');
  const t=node('table');if(caption)t.append(node('caption',caption));const thead=node('thead'),tr=node('tr');
  for(const [label] of columns){const th=node('th',label);th.scope='col';tr.append(th);}thead.append(tr);t.append(thead);
  const body=node('tbody');for(const row of rows){const line=node('tr');for(const [,key] of columns){const value=typeof key==='function'?key(row):row[key];const td=node('td');td.append(value instanceof Node?value:node('span',fmt(value)));line.append(td);}body.append(line);}t.append(body);wrapper.append(t);root.append(wrapper);
}
function details(root,label,child){const el=node('details');el.append(node('summary',label),child);root.append(el);}
function amount(value,unit='kg',empty='미입력'){return value==null?empty:`${fmt(value)}${unit}`;}
function routeButton(label,route,action){const a=node('a',label,'button secondary small');a.href='#/'+route;a.dataset.route=route;if(action)a.dataset.action=action;return a;}
export function renderInputs(context){
  const a=context.attendance,root=$('staff-summary');root.replaceChildren();
  for(const [label,value] of [['등록 인원',`${fmt(a.registered_population)}명`],['급식 용량',`${fmt(context.meal_capacity)}식`]]){const item=node('div');item.append(node('span',label),node('strong',value));root.append(item);}
  const menu=context.weekly_menu.filter(m=>m.date===context.target_date&&m.meal_type==='lunch');
  $('menu-preview').replaceChildren(node('p',menu.map(m=>m.menu_name).join(' · ')||'선택한 날짜의 식단이 없습니다.','data-title'),node('p',`${context.target_date} · 점심`,'data-subtitle'));
  const dates=[...new Set(context.weekly_menu.map(m=>m.date))].sort();
  if(!menu.length)$('menu-preview').append(node('p','운영일을 변경하거나 이 날짜가 포함된 식단 파일을 불러오세요.','notice danger'));
  $('menu-table').replaceChildren();table($('menu-table'),[['날짜','date'],['메뉴','menu_name']],context.weekly_menu,`${dates[0]||''} ~ ${dates.at(-1)||''}`);
  const inventory=context.inventory;const count=new Set(inventory.map(i=>i.ingredient)).size;
  $('inventory-preview').replaceChildren(node('p',`${fmt(count)}개 품목 · ${fmt(inventory.length)}개 재고 묶음`,'data-title'),node('p',`입력 기준일 ${context.as_of}`,'data-subtitle'));
  $('inventory-preview').append(node('p','사용 가능량과 기한 위험은 운영 계획에서 확인합니다.','muted'));
  $('inventory-table').replaceChildren();table($('inventory-table'),[['식재료','ingredient'],['재고',r=>`${fmt(r.current_stock)}${r.unit}`],['기한','expiry_date']],inventory,'불러온 재고 · 실제 입고·기한 확인 필요');
  text('menu-source',context.menu_uploaded?'직접 업로드':'시연 자료');text('inventory-source',context.inventory_uploaded?'직접 업로드':'시연 자료');
  text('event-date-help',`‘내일’은 선택한 운영일(${context.target_date})로 해석합니다. 해석된 날짜를 확인하세요.`);
}
export function renderEvents(id,data){
  const root=$(id);root.replaceChildren();
  root.append(node('p',data.needs_review?'날짜 또는 내용 확인이 필요합니다. 더 구체적으로 입력한 뒤 다시 확인하세요.':data.message,'notice'+(data.needs_review?' danger':' info')));
  table(root,[['날짜',r=>r.date?(r.end_date?`${r.date} ~ ${r.end_date}`:r.date):'날짜 확인 필요'],['해석한 내용','label'],['적용','status']],data.rows,'변경사항 해석');
  root.append(node('p',`선택일 운영 인원 변화 ${signed(data.attendance_delta)}명 · 조리량·재료 영향은 반영 후 계산합니다.`,'muted'));
}
function issueList(rows){const list=node('ul',null,'issue-list');for(const issue of rows){const li=node('li');li.append(node('span',issue.level,'level'+(issue.level==='차단'?' block':issue.level==='참고'?' info':'')),node('strong',issue.title),node('p',issue.action));list.append(li);}return list;}
export function renderPlan(plan){
  $('planner-empty').hidden=!!plan;$('plan-content').hidden=!plan;if(!plan){text('plan-save-state','');return;}
  text('plan-save-state',`${plan.calculation} · ${plan.saved?'저장됨':'저장 미완료'}`);
  const summary=node('div',null,'summary-banner'+(plan.blocked?' blocked':''));summary.append(node('p','최종 운영 권고','summary-kicker'),node('h2',plan.outcome));
  summary.append(node('p','다음 조치 · '+plan.next_action,'next-action'));
  if(plan.ood){const notice=node('div',null,'notice danger');notice.append(node('strong','이 사업장에서는 검증되지 않은 예측입니다.'),node('p','예측은 참고용입니다. 운영 인원과 사업장 적용 가능성을 먼저 확인하세요.'),routeButton('운영 인원 확인','create','staff'));summary.append(notice);}
  const metrics=node('div',null,'metric-grid');
  for(const [label,value,unit,help,klass] of [['예상 식수',plan.model_diners,'명',plan.ood?'참고용 · 검증 범위 밖':'모델 예측 · 신뢰도 미산정',''],['이벤트 반영 식수',plan.operating_diners,'명',plan.events.attendance_delta?`인원 변경 ${signed(plan.events.attendance_delta)}명 반영`:'운영 변경사항 반영 기준',''],['권장 조리량 · 검토용',plan.review_servings,'식','미확정 · 운영 조건 확인 필요','review']]){
    const box=node('div',null,'metric-card '+klass);const strong=node('strong',fmt(value,'계산 미완료'));if(value!=null)strong.append(node('em',unit));box.append(node('span',label),strong,node('small',help));metrics.append(box);
  }summary.append(metrics);$('plan-summary').replaceChildren(summary);
  const cooking=$('cooking-card');cooking.replaceChildren(node('h2','조리 계획'),node('p',plan.menus.join(' · ')||'선택일 식단 확인 필요','data-title'));
  metric(cooking,'안전 여유분',amount(plan.margin_pct,'%'));metric(cooking,'급식 용량',amount(plan.capacity,'식'));cooking.append(node('p',plan.reason,'muted'));
  const check=node('ul',null,'check-list');for(const c of plan.checks){const li=node('li');li.append(node('span',c.label),node('span',`${c.status}${c.actual!=null?' · '+fmt(c.actual)+c.unit:''}${c.minimum!=null?' / 최소 '+fmt(c.minimum)+c.unit:''}${c.maximum!=null?' / 최대 '+fmt(c.maximum)+c.unit:''}${c.matched?.length?' · '+c.matched.join(', '):''}`));check.append(li);}if(plan.checks.length)details(cooking,'영양·알레르기 조건 확인',check);else cooking.append(node('p','영양·알레르기 검증 자료를 확인해야 합니다.','notice'));
  const risk=$('risk-card');risk.replaceChildren(node('h2','위험과 다음 조치'));
  const primary=plan.issues.filter(i=>i.level!=='참고'),reference=plan.issues.filter(i=>i.level==='참고');
  risk.append(issueList(primary));if(reference.length)details(risk,`참고 · 재고 활용 ${reference.length}건`,issueList(reference));if(!plan.issues.length)risk.append(node('p','보고된 위험이 없습니다. 최종 운영 조건은 현장에서 확인하세요.','muted'));
  if(plan.affected_menus?.length){const view=node('div');table(view,[['날짜','date'],['영향 메뉴','menu'],['재료','ingredient']],plan.affected_menus,'위험이 연결된 메뉴');details(risk,'영향 메뉴 보기',view);}
  if(plan.price_changes?.length){risk.append(node('p','가격 위험 · '+plan.price_changes.map(r=>`${r.ingredient} ${signed(r.change_pct)}%`).join(' / '),'notice'));const view=node('div');table(view,[['식재료','ingredient'],['현재 가격',r=>`${fmt(r.current)}원/${r.unit}`],['비교 가격',r=>`${fmt(r.reference)}원/${r.unit}`],['변화',r=>`${signed(r.change_pct)}%`]],plan.price_changes,'가격 변동');details(risk,'가격 근거 보기',view);}
  if(plan.supply_risks?.length){risk.append(node('p','공급 위험 · '+plan.supply_risks.map(r=>r.ingredient).join(' / ')+' 입고 일정을 확인하세요.','notice danger'));const view=node('div');table(view,[['식재료','ingredient'],['시작일','date'],['종료일',r=>r.end_date||'종료 미정']],plan.supply_risks,'공급처·입고 일정 확인 필요');details(risk,'공급 위험 기간 보기',view);}
  const procurement=$('procurement-card');procurement.replaceChildren(node('h2','발주·재고 검토'),node('p','추가 확보량은 계산상 부족분입니다. 입고와 유통기한을 확인하기 전 확정 발주량으로 사용할 수 없습니다.','muted'));
  table(procurement,[['식재료','ingredient'],['필요량',r=>amount(r.required_kg)],['사용 가능 재고',r=>amount(r.usable_kg,'kg','검증 자료 없음')],['추가 확보 필요량',r=>amount(r.additional_kg)],['예정 발주',r=>amount(r.planned_kg)],['과다·부족 판단','order_review']],plan.materials,'재료별 계산량 · kg 기준');
  const arrivals=node('div');table(arrivals,[['식재료','ingredient'],['기록된 재고',r=>amount(r.stock_kg)],['입고 예정',r=>r.arrival_date||'미입력'],['입고 확인','arrival']],plan.materials,'재고·입고 상세');details(procurement,'재고·입고 상세 보기',arrivals);
  const alternatives=$('alternatives-card');alternatives.replaceChildren();
  const eligible=plan.candidates.filter(c=>c.eligible),excluded=plan.candidates.filter(c=>!c.eligible);
  const candidate=c=>{const item=node('div',null,'candidate'+(!c.eligible?' unavailable':''));item.append(node('h3',`${c.original_menu} → ${c.menu}`),node('span',c.status,'badge subtle'),node('p',`영양: ${c.nutrition} · 재고: ${c.inventory} · ${c.cost}`));if(c.shortages.length)item.append(node('p',c.shortages.map(s=>`${s.ingredient} ${fmt(s.kg)}kg 부족`).join(' / ')));if(c.reasons.length)item.append(node('p',c.reasons.join(' · '),'notice danger'));return item;};
  if(eligible.length)eligible.forEach(c=>alternatives.append(candidate(c)));else alternatives.append(node('p','현재 검토 가능한 대체 메뉴가 없습니다.','muted'));
  if(excluded.length){const list=node('div');excluded.forEach(c=>list.append(candidate(c)));details(alternatives,`사용 불가 후보 ${excluded.length}건과 제외 사유`,list);}
  alternatives.append(node('p','대체 메뉴 적용은 지원하지 않습니다. 선택·재검증 절차를 거친 뒤 현장에서 결정하세요.','muted'));
  const changes=$('plan-changes');changes.replaceChildren();if(plan.changes){const c=plan.changes,box=node('section',null,'panel');box.append(node('h2','변경 전후'),node('p',`운영 기준 ${fmt(c.old_diners)} → ${fmt(c.new_diners)}명 (${signed(c.diners_delta)}명)`),node('p',`검토용 조리량 ${fmt(c.old_servings)} → ${fmt(c.new_servings)}식 (${signed(c.servings_delta)}식)`));if(c.materials.length)box.append(node('p','필요 재료 변화 · '+c.materials.map(m=>`${m.ingredient} ${signed(m.delta_kg)}kg`).join(' / '),'changed'));changes.append(box);}
  $('changes-details').hidden=!plan.changes;
  text('ack-status',plan.acknowledged_at?`${stamp(plan.acknowledged_at)} · 권고 내용 열람 기록됨`:'권고 내용을 읽은 뒤 확인을 남겨 주세요.');
  text('ack-button',plan.acknowledged_at?'운영 결과 입력 →':'운영 계획 확인');
  $('retry-save').hidden=plan.saved;text('replan-date-help',`‘내일’은 이 계획의 운영일(${plan.target_date})로 해석합니다.`);
  $('plan-data-basis').replaceChildren(node('p',`식단: ${plan.sources.menu} / 재고: ${plan.sources.inventory} / 입력 기준일: ${plan.sources.as_of}`),node('p','모델이 예측 범위를 계산하지 않아 상·하한은 표시하지 않습니다. 학습 범위 안의 입력도 정확도를 보증하지 않습니다.'));
}
export function renderActual(record){
  const root=$('actual-summary');root.replaceChildren(node('h2',record?'저장된 운영 결과':'저장 결과'));
  if(!record){root.append(node('p','현장 기록을 저장하면 예측과 실제 결과를 비교할 수 있습니다.','muted'));return;}
  root.append(node('p',`${stamp(record.updated_at||record.created_at)} ${record.updated_at?'정정 저장':'저장'}`,'time-label'));
  const kpis=node('div',null,'result-kpis');
  for(const [label,value,help] of [['예측 대비 차이',signed(record.model_difference)+(record.model_difference==null?'':'명'),'실제 식수 − 모델 예측'],['초과 조리량',amount(record.overprep_servings,'식'),'실제 식수보다 더 조리한 수량']]){const card=node('div',null,'result-kpi');card.append(node('span',label),node('strong',value),node('small',help));kpis.append(card);}
  const waste=node('div',null,'result-kpi waste-kpi');waste.append(node('span','잔식 · 잔반 · 식재료 폐기'));
  for(const [label,key] of [['배식 전 잔식','unserved_leftover_kg'],['식판 잔반','plate_waste_kg'],['식재료 폐기','ingredient_waste_kg']])metric(waste,label,amount(record[key],'kg','미측정'));
  kpis.append(waste);root.append(kpis,node('p',`급식 부족 · ${record.shortage?'있음':'없음'}`,record.shortage?'notice danger':'muted'));
  const comparison=node('div');for(const [label,value] of [['모델 원본 예측',amount(record.predicted_diners,'명','연결 자료 없음')],['운영 조정 기준',amount(record.operating_diners,'명','연결 자료 없음')],['실제 식수',amount(record.actual_diners,'명')],['운영 기준 대비',signed(record.operating_difference)+(record.operating_difference==null?'':'명')],['실제 조리량',amount(record.prepared_servings,'식')]])metric(comparison,label,value);details(root,'입력값·비교 기준 상세',comparison);
  if(record.notes)root.append(node('p',record.notes,'notice info'));
  root.append(node('p','비교값은 실제 식수에서 각 기준을 뺀 값입니다. 초과 조리량은 음식 무게와 다른 지표입니다.','muted'));
  if(record.corrections?.length){const list=node('div');for(const correction of record.corrections)list.append(node('p',`${stamp(correction.created_at)} · ${correction.reason}`));details(root,`정정 이력 ${record.corrections.length}건`,list);}
}
export function renderHistory(rows){
  const root=$('history');root.replaceChildren(node('h2','최근 운영 이력'),node('p','선택 사업장의 최근 기록입니다. 시연 기록은 실제 운영·학습 집계에서 제외됩니다.','history-scope'));
  for(const [demo,label] of [[true,'시연 기록'],[false,'실제 운영 기록']]){
    const items=rows.filter(r=>Boolean(r.is_demo)===demo);if(!items.length)continue;
    table(root,[['운영일','target_date'],['실제 식수',r=>amount(r.actual_diners,'명')],['초과 조리',r=>amount(r.overprep_servings,'식')],['잔식',r=>amount(r.unserved_leftover_kg,'kg','미측정')],['잔반',r=>amount(r.plate_waste_kg,'kg','미측정')],['식재료 폐기',r=>amount(r.ingredient_waste_kg,'kg','미측정')],['부족',r=>r.shortage?'있음':'없음'],['기록',r=>{const b=node('button','상세 보기','secondary small');b.type='button';b.dataset.historyDate=r.target_date;b.dataset.planId=r.plan_request_id||'';b.setAttribute('aria-label',`${r.target_date} 기록 상세 보기`);return b;}]],items,label);
  }
  if(!rows.length)root.append(node('p','아직 저장된 운영 결과가 없습니다.','muted'));
}
