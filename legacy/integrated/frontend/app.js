/* All operational arithmetic lives on the server. This file renders API results. */
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = value => Number(value).toLocaleString('ko-KR', {maximumFractionDigits:3});
const kg = value => `${fmt(value)}kg`;
const clone = value => JSON.parse(JSON.stringify(value));
const state = {plan:null, input:null, busy:false, filter:'all', scenario:'normal'};
const storageKey = 'lastplate-integration-v1';
const show = (id, text) => { $(id).textContent = text; };
const line = (label, value) => `<div class="key-value-line"><span class="kv-label">${esc(label)}</span><span class="kv-val">${esc(value)}</span></div>`;
const badge = (text, ok) => `<span class="status-badge ${ok ? 'status-ok' : 'status-warn'}">${esc(text)}</span>`;
const deliveryText = {on_time:'조리 전 입고 예정',late:'조리 후 도착',unconfirmed:'납기 미확인'};

async function api(path, method='GET', body) {
  const response = await fetch(`/api/v1${path}`, {
    method, headers:body ? {'Content-Type':'application/json'} : {},
    body:body ? JSON.stringify(body) : undefined, signal:AbortSignal.timeout(30000)
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map(x => `${x.loc.join('.')}: ${x.msg}`).join('\n') : data.detail;
    throw new Error(`${response.status}: ${detail || '요청에 실패했습니다.'}`);
  }
  return data;
}

function controls() {
  document.querySelectorAll('button, select, input').forEach(el => { el.disabled = state.busy; });
  if (state.plan) $('btn-request-approval').disabled = state.busy || !state.plan.review_allowed || state.plan.review_status === 'reviewed_demo';
}
async function task(action) {
  if (state.busy) return;
  state.busy = true; controls(); $('app-error').hidden = true;
  show('connection-status','서버 계산·저장 중…');
  try { await action(); }
  catch (error) {
    show('app-error', `${error.message}\n연결 실패 시 임의 결과로 대체하지 않습니다. 서버 실행 상태를 확인하세요. 오래된 운영안 오류는 새로고침 후 다시 시도하세요.`);
    $('app-error').hidden = false;
  } finally {
    state.busy = false; controls();
    show('connection-status', state.plan ? `서버 저장 완료 · 운영안 ${state.plan.id.slice(0,8)} · 시뮬레이션 시각 ${state.input.current_time}` : '연결되지 않았습니다. 서버 확인 후 새로고침하세요.');
  }
}
function remember() {
  try { localStorage.setItem(storageKey, JSON.stringify({id:state.plan.id, scenario:state.scenario})); } catch (_) { /* storage optional */ }
}
async function accept(plan) {
  const input = await api(`/operation-plans/${plan.id}/input`);
  state.plan = plan; state.input = input;
  remember(); render(); document.body.classList.add('ready');
}
async function create(input) { await accept(await api('/operation-plans','POST',input)); }
async function scenario(name) {
  const input = await api(`/demo/input?scenario=${encodeURIComponent(name)}`);
  const plan = await api('/operation-plans','POST',input);
  state.scenario = name;
  await accept(plan);
  show('copilot-messages-box',''); chat('bot','새 시나리오입니다. 계산 결과에 대해 질문해 보세요. 규칙 기반 설명이며 LLM이나 운영 문서 검색은 연결되지 않았습니다.');
}
function navigate(screen) {
  document.querySelectorAll('.screen-pane').forEach(el => el.classList.toggle('active',el.id === `screen-${screen}`));
  document.querySelectorAll('[data-screen]').forEach(el => {
    const active = el.dataset.screen === screen;
    el.classList.toggle('active',active);
    if (active) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current');
  });
  window.scrollTo({top:0,behavior:'instant'});
}
function rationale() {
  const r = state.plan.result, p = r.policy;
  const basis = state.input.forecast.interval_method === 'point_only' ? 'ML 점 예측 (구간 없음)' : '시연용 범위 (신뢰수준 없음)';
  return `${basis}: ${fmt(r.prediction.mid)}명. 확정 변동 합계 ${r.event_delta >= 0 ? '+' : ''}${r.event_delta}명.\n`+
    `권장량 = max(예측 상한 ${fmt(r.prediction.upper)}, 예측 중간값+안전여유 ${fmt(p.buffered_mid)})를 ${p.cooking_unit}식 단위로 올림 = ${r.recommended_target}식.\n`+
    `현재 적용 ${r.target}식. 수요 분위수나 부족 확률을 보장하는 계산은 아닙니다.`;
}
function render() {
  const p = state.plan, r = p.result, f = state.input.forecast;
  $('scenario-select-desktop').value = state.scenario;
  $('scenario-select-mobile').value = state.scenario;
  document.querySelector('.badge-demo').textContent = f.source_kind === 'ml' ? '실제 ML 추론 · 운영 입력은 시연용' : '시연 입력 · 백엔드 연결됨';
  show('home-serving-number',fmt(r.recommended_target));
  show('hero-desc-text',`변동 반영 예측 ${fmt(r.prediction.mid)}명 · 권장 ${fmt(r.recommended_target)}식 · 적용 ${fmt(r.target)}식. 현재 재고와 제때 입고될 경우를 구분하여 검토합니다.`);
  $('home-status-badge-container').innerHTML = badge(p.review_allowed ? '입고 가정하에 검토 가능' : '운영 경고 확인 필요',p.review_allowed);
  $('source-summary').innerHTML = line('예측 출처', f.source_kind === 'ml' ? '첨부 LightGBM 모델' : 'UI 시연용 고정 예측')+
    line('모델 버전',f.model_version)+line('예측 방식',f.interval_method === 'point_only' ? '단일 값 · 예측구간 없음' : '시연용 범위 · 신뢰수준 없음')+
    line('기준 확인',r.operating_rules_verified ? '예시 운영 기준 입력됨' : '운영 기준 미확인');
  $('home-metrics').innerHTML = '<h3>운영 핵심 지표</h3>'+line('변동 전 예측',`${fmt(r.baseline_prediction.mid)}명`)+
    line('변동 후 예측',`${fmt(r.prediction.mid)}명`)+line('적용 조리량',`${fmt(r.target)}식`)+
    line('발주 필요',`${p.purchase_recommendations.length}개 품목`)+line('검토 상태',p.review_status === 'reviewed_demo' ? '검토 완료 (시연)' : '검토 대기');
  $('operation-todos').innerHTML = [...p.alerts,...p.inventory_advisories].map(a =>
    `<li class="todo-item"><div class="todo-info">${badge(a.severity === 'critical' ? '확인 필요' : '안내',false)}<span class="todo-text">${esc(a.message)}</span></div></li>`).join('') || '<li class="todo-item">추가 경고가 없습니다.</li>';
  show('company-events-count',`${r.events.length}건`);
  $('company-events-list').innerHTML = r.events.map(e => `<li><span>${esc(e.note || e.id)} · ${e.delta >= 0 ? '+' : ''}${e.delta}명 · ${esc({confirmed:'확정',pending:'미확정',cancelled:'취소'}[e.status])}</span>${e.status !== 'cancelled' ? `<button class="btn btn-secondary btn-sm" type="button" data-cancel-event="${esc(e.id)}">취소</button>` : ''}</li>`).join('') || '<li>추가 인원 변동이 없습니다.</li>';
  $('plan-summary').innerHTML = line('기준 예측',`${fmt(f.mid)}명`)+line('변동 반영 예측',`${fmt(r.prediction.mid)}명`)+
    line('예측 범위',f.interval_method === 'point_only' ? '제공하지 않음' : `${fmt(r.prediction.lower)}~${fmt(r.prediction.upper)}명 (시연)`)+
    line('기본 안전여유',`${r.policy.safety_buffer_people}명`)+line('조리 단위',`${r.policy.cooking_unit}식`)+
    f.warnings.map(w => `<p class="form-hint">${esc(w)}</p>`).join('');
  show('plan-recommended-val',`${fmt(r.recommended_target)}식`);
  $('input-custom-plan').value = r.target;
  $('input-custom-plan').step = r.policy.cooking_unit;
  show('plan-buffer-val',`${fmt(r.target-r.prediction.mid)}식`);
  show('btn-reset-plan-val',`권장값(${fmt(r.recommended_target)}식)으로 복원`);
  show('plan-validation-alert',p.review_allowed ? '입고 가정 시 적용량 조리 가능. 실제 발주 및 입고 여부를 확인하세요.' : '용량·납기·안전여유·운영 기준 경고를 확인하세요.');
  $('accordion-rationale-body').textContent = rationale();
  $('accordion-rationale-body').style.whiteSpace = 'pre-line';
  $('btn-accordion-rationale').firstElementChild.textContent = `왜 ${fmt(r.recommended_target)}식인가요? (계산 근거)`;
  $('batch-timeline').innerHTML = '<h3>배치별 변경 가능량</h3><p class="form-hint">현재 재고 기준 실제 가능량 / 권장 발주가 제때 도착했다고 가정한 가능량입니다.</p>'+r.menus.map((m,i) => {
    const projected = p.projected_after_purchase.menus[i];
    return `<div class="batch-card"><strong>${esc(m.menu)}</strong> · 목표 ${m.target}식 · 현재 가능 ${m.final}식 · 입고 가정 ${projected.final}식`+
      m.fixed_batches.map(b => `<div>${esc(b.name)}: ${b.qty}식 잠금 (변경 불가${b.quantity_is_assumed ? ', 실적 미입력으로 기존 계획 사용' : ''})</div>`).join('')+
      m.future.map((b,j) => `<div>${esc(b.name)}: ${esc(b.start.slice(11,16))} · 기존 ${b.planned} → 현재 가능 ${b.qty} (${b.change>=0?'+':''}${b.change}) / 입고 가정 ${projected.future[j].qty}식</div>`).join('')+'</div>';
  }).join('');
  $('setting-capacity').value = state.input.menus[0].batches.reduce((s,b)=>s+b.capacity,0);
  $('setting-buffer').value = state.input.policy.safety_buffer_people;
  $('setting-time').value = state.input.current_time.slice(0,16);
  $('ml-menu').value = state.input.menus.map(m=>m.name).join(' ');
  if (f.input_summary) ['employees','vacation','business_trip','work_from_home','overtime'].forEach(k => { $(`ml-${k}`).value = f.input_summary[k]; });
  renderInventory();
  show('copilot-meta-pred',`${fmt(r.prediction.mid)}명`); show('copilot-meta-plan',`${fmt(r.target)}식`);
}

function renderInventory() {
  if (!state.plan) return;
  const p = state.plan, r = p.result;
  const buys = new Map(p.purchase_recommendations.map(x=>[x.ingredient,x]));
  const priority = new Set(p.inventory_advisories.filter(x=>x.code==='USE_FIRST_EXPIRING_STOCK').map(x=>x.ingredient));
  const search = $('inv-search-input').value.trim();
  const rows = r.inventory.filter(x => x.ingredient.includes(search) && (state.filter==='all' ||
    (state.filter==='order_needed' && buys.has(x.ingredient)) || (state.filter==='fefo_priority' && priority.has(x.ingredient))));
  show('count-filter-all',r.inventory.length); show('count-filter-order',buys.size); show('count-filter-fefo',priority.size);
  show('inv-summary-plan-val',fmt(r.target)); show('inv-summary-order-count',`${buys.size}개 품목`);
  const reviewed = p.review_status==='reviewed_demo';
  ['inv-summary-order-status','draft-panel-badge'].forEach(id => show(id,reviewed ? '검토 완료 (시연)' : '검토 대기'));
  function cells(row) {
    const buy = buys.get(row.ingredient), item = state.input.inventory.find(x=>x.ingredient===row.ingredient);
    const grams = state.input.menus.reduce((s,m)=>s+(m.recipe_g[row.ingredient]||0)*m.servings_per_guest,0);
    return [row.ingredient,`${fmt(grams)}g`,kg(row.needed_for_equipment_plan_kg),kg(row.available_kg),kg(row.additional_kg_for_equipment_plan),
      kg(item?.order_unit_kg ?? .001),kg(buy?.recommended_order_kg || 0),buy ? deliveryText[buy.delivery_status] : priority.has(row.ingredient) ? '우선 소진' : '확보'];
  }
  $('inventory-table-tbody').innerHTML = rows.map(row=>`<tr>${cells(row).map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('');
  $('inventory-mobile-container').innerHTML = rows.map(row=>{
    const c = cells(row); return `<div class="inv-mobile-card"><strong>${esc(c[0])}</strong>${line('필요 / 가용',`${c[2]} / ${c[3]}`)}${line('부족 / 권장 발주',`${c[4]} / ${c[6]}`)}${line('상태',c[7])}</div>`;
  }).join('');
  $('inv-empty-message').style.display = rows.length ? 'none' : 'block';
  $('fefo-lots-container').innerHTML = p.stock_allocations.map(row=>
    `<div class="notice-row"><strong>${esc(row.ingredient)}</strong> · ${row.source==='net_available' ? '입력 가용량' : '실물'} ${kg(row.physical_kg)} − 예약 ${kg(row.reserved_kg)} − 기한 경과 ${kg(row.expired_kg)} = 가용 ${kg(row.usable_kg)}`+
    row.lots.map(l=>`<div class="lot-box"><span>${esc(l.lot_id)} · 기한 ${esc(l.expires_on||'미입력')}</span><span>배정 ${kg(l.allocated_kg)} / 잔여 ${kg(l.remaining_kg)}</span></div>`).join('')+'</div>').join('');
  $('draft-items-container').innerHTML = p.purchase_recommendations.map(b=>
    `<div class="notice-row"><strong>${esc(b.ingredient)} ${kg(b.recommended_order_kg)} (${b.package_count}포장)</strong><p>부족 ${kg(b.shortage_kg)} ÷ 포장 ${kg(b.order_unit_kg)} → 올림</p><p>${esc(deliveryText[b.delivery_status])} · 납기 ${esc(b.expected_delivery_at||'미입력')} · 필요 시각 ${esc(b.required_by||'미확인')}</p>${b.estimated_cost != null ? `<p>예시 단가 기준 ${fmt(b.estimated_cost)}원</p>` : ''}</div>`).join('') || '추가 발주가 필요하지 않습니다.';
  show('draft-action-alert', reviewed ? '검토 상태가 서버에 저장되었습니다. 실제 발주·입고·재고 차감은 수행하지 않았습니다.' : p.review_allowed ? '설정된 납기대로 도착한다는 가정에서 검토 가능합니다. 실제 발주 전 현장 확인이 필요합니다.' : '검토 완료 제한: 용량 부족, 납기 미확인/지연, 권장량 미달, 또는 운영 기준 미확인.');
}
async function adjust(value) {
  if (value !== null && (!Number.isInteger(value) || value < 0 || value > 100000 || value % state.input.policy.cooking_unit))
    throw new Error(`조리량은 0~100,000 사이 ${state.input.policy.cooking_unit}식 단위로 입력하세요.`);
  await accept(await api(`/operation-plans/${state.plan.id}/adjust`,'POST',{applied_servings:value,current_time:state.input.current_time}));
}
function chat(role, text) {
  const el=document.createElement('div'); el.className=`chat-msg chat-msg-${role}`; el.textContent=text;
  $('copilot-messages-box').appendChild(el); el.scrollIntoView({block:'nearest'});
}
function answer(question) {
  if (!state.plan || !question.trim()) return;
  chat('user',question);
  let text;
  if (/발주|돼지/.test(question)) text=state.plan.purchase_recommendations.map(b=>`${b.ingredient}: 부족 ${kg(b.shortage_kg)}, ${kg(b.order_unit_kg)} 포장 ${b.package_count}개 = ${kg(b.recommended_order_kg)}. ${deliveryText[b.delivery_status]}.`).join('\n')||'추가 발주가 필요하지 않습니다.';
  else if (/재고|기한|소진|양배추/.test(question)) text=state.plan.stock_allocations.map(i=>`${i.ingredient}: 가용 ${kg(i.usable_kg)}, 배정 ${kg(i.allocated_kg)}. 예약·기한 경과분은 제외하며 유효 재고를 기한순으로 배정합니다.`).join('\n');
  else if (/조리|권장|근거|왜/.test(question)) text=rationale();
  else text='현재 지원하는 질문은 권장 조리량, 발주량, 우선 소진 재고입니다. 자유 대화용 LLM은 연결되지 않았습니다.';
  chat('bot',`[운영안 ${state.plan.id.slice(0,8)}의 계산 결과]\n${text}\n${state.input.policy.operating_rules_verified ? '운영 기준은 시연용 입력입니다.' : '운영 기준이 미확인 상태입니다.'}`);
}

document.querySelectorAll('[data-screen]').forEach(el=>el.addEventListener('click',()=>navigate(el.dataset.screen)));
document.querySelectorAll('[data-action]').forEach(el=>el.addEventListener('click',()=>{
  const action=el.dataset.action;
  if(action==='ask-copilot-why'){navigate('copilot');answer('권장 조리량의 근거는 무엇인가요?');}
  else if(action.includes('plan')){navigate('plan');if(action==='go-plan-basis')$('btn-accordion-rationale').click();}
  else navigate('inventory');
}));
$('scenario-select-desktop').addEventListener('change',e=>task(()=>scenario(e.target.value)));
$('scenario-select-mobile').addEventListener('change',e=>task(()=>scenario(e.target.value)));
$('btn-reset-state').addEventListener('click',()=>task(()=>scenario('normal')));
$('event-form').addEventListener('submit',e=>{e.preventDefault();task(async()=>{
  const delta=Number($('event-delta').value);
  if(!Number.isInteger(delta)||delta===0)throw new Error('0이 아닌 정수로 증감 인원을 입력하세요.');
  await accept(await api(`/operation-plans/${state.plan.id}/events`,'POST',{
    current_time:state.input.current_time,event:{id:crypto.randomUUID(),status:'confirmed',delta,note:$('event-note').value}
  })); $('event-note').value='';
});});
$('company-events-list').addEventListener('click',e=>{
  const button=e.target.closest('[data-cancel-event]'); if(!button)return;
  task(async()=>{const event=state.input.events.find(x=>x.id===button.dataset.cancelEvent);
    await accept(await api(`/operation-plans/${state.plan.id}/events`,'POST',{current_time:state.input.current_time,event:{...event,status:'cancelled'}}));});
});
$('ml-form').addEventListener('submit',e=>{e.preventDefault();task(async()=>{
  const input=clone(state.input), request={site_id:input.site_id,meal_date:input.meal_date,meal_type:input.meal_type,menu:$('ml-menu').value};
  ['employees','vacation','business_trip','work_from_home','overtime'].forEach(k=>{request[k]=Number($(`ml-${k}`).value);});
  input.forecast=await api('/forecasts/predict','POST',request); input.applied_servings=null;
  await create(input);
});});
$('settings-form').addEventListener('submit',e=>{e.preventDefault();task(async()=>{
  const input=clone(state.input), cap=Number($('setting-capacity').value), buffer=Number($('setting-buffer').value);
  if(!Number.isInteger(cap)||cap<0||!Number.isInteger(buffer)||buffer<0)throw new Error('한도와 안전여유는 0 이상의 정수여야 합니다.');
  input.current_time=$('setting-time').value+':00+09:00'; input.policy.safety_buffer_people=buffer;input.applied_servings=null;
  for(const menu of input.menus){
    if(menu.batches.some(b=>b.status!=='planned'||new Date(b.start)<=new Date(state.input.current_time))) {
      if(cap!==menu.batches.reduce((s,b)=>s+b.capacity,0))throw new Error('시작된 배치의 용량은 화면에서 변경할 수 없습니다.');
    } else if(menu.batches.length===1){menu.batches[0].capacity=cap;menu.batches[0].planned=Math.min(menu.batches[0].planned,cap);}
  }
  await create(input);
});});
$('btn-step-minus').addEventListener('click',()=>{$('input-custom-plan').value=Math.max(0,Number($('input-custom-plan').value)-state.input.policy.cooking_unit);});
$('btn-step-plus').addEventListener('click',()=>{$('input-custom-plan').value=Number($('input-custom-plan').value)+state.input.policy.cooking_unit;});
$('btn-proceed-inventory').addEventListener('click',()=>task(async()=>{await adjust(Number($('input-custom-plan').value));navigate('inventory');}));
$('btn-reset-plan-val').addEventListener('click',()=>task(()=>adjust(null)));
$('btn-accordion-rationale').addEventListener('click',()=>{
  const open=$('accordion-rationale-body').classList.toggle('open');$('btn-accordion-rationale').setAttribute('aria-expanded',String(open));show('accordion-arrow',open?'▲':'▼');
});
$('inv-search-input').addEventListener('input',renderInventory);
document.querySelectorAll('[data-filter]').forEach(el=>el.addEventListener('click',()=>{
  state.filter=el.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===el));renderInventory();
}));
$('btn-clear-search-filter').addEventListener('click',()=>{$('inv-search-input').value='';document.querySelector('[data-filter="all"]').click();});
$('btn-request-approval').addEventListener('click',()=>task(async()=>accept(await api(`/operation-plans/${state.plan.id}/review`,'POST'))));
$('copilot-form').addEventListener('submit',e=>{e.preventDefault();answer($('copilot-input').value);$('copilot-input').value='';});
document.querySelectorAll('.chip-btn').forEach(el=>el.addEventListener('click',()=>answer(el.textContent)));

task(async()=>{
  let saved;try{saved=JSON.parse(localStorage.getItem(storageKey));}catch(_){}
  if(saved?.id){
    let restored;
    try { restored=await api(`/operation-plans/${encodeURIComponent(saved.id)}`); }
    catch(error){if(!error.message.startsWith('404:'))throw error;}
    if(restored?.result.forecast_metadata){
      const latest=await api(`/operation-plans/latest?site_id=${encodeURIComponent(restored.site_id)}&meal_date=${restored.meal_date}&meal_type=${restored.meal_type}`);
      state.scenario=saved.scenario||'normal';await accept(latest);return;
    }
  }
  await scenario('normal');
});
