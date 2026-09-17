import {initMonthly} from './monthly.js?v=4';
import {api} from './api/lastplateApi.js?v=4';
import {$,fmt,stamp,node,text,renderInputs,renderEvents,renderPlan,renderActual,renderHistory,renderSectionState} from './components/cards.js?v=4';

const staff=['vacation','business_trip','work_from_home','overtime'];
const actualNumbers=['actual_diners','prepared_servings','unserved_leftover_kg','plate_waste_kg','ingredient_waste_kg'];
const sectionLabels={sites:'사업장',context:'입력 자료',plans:'저장 계획 목록',plan:'운영 계획',actual:'운영 결과',history:'최근 이력'};
const initialSections=()=>Object.fromEntries(Object.keys(sectionLabels).map(name=>[name,{status:'idle'}]));
const state={selection:null,context:null,plan:null,record:null,plans:[],historyRows:[],screen:'create',busy:false,loading:false,correcting:false,preview:null,createPreview:null,sections:initialSections()};
let loadVersion=0,monthly=null;
const reads={};
const drafts=new Map();
const clone=value=>structuredClone(value);
const key=()=>state.selection?`${state.selection.site}|${state.selection.date}|${state.selection.plan||''}`:'';
const events=id=>$(id).value.split('\n').map(s=>s.trim()).filter(Boolean);
const eventKey=(forPlan=false)=>JSON.stringify([state.selection?.site,state.selection?.date,forPlan?state.plan?.id:state.context?.base_request_id,events(forPlan?'replan-events':'events')]);
const eventReady=(forPlan=false)=>{const value=forPlan?state.preview:state.createPreview;return !!value&&!value.data.needs_review&&value.key===eventKey(forPlan);};
function invalidateEvents(){state.createPreview=null;state.preview=null;$('create-event-preview').replaceChildren();$('replan-event-preview').replaceChildren();}
function status(id,message,error=false){text(id,message);$(id).classList.toggle('error',error);$(id).classList.toggle('success',!error&&!!message);$(id).setAttribute('role',error?'alert':'status');if(error)$(id).focus();}
function syncActions(){
  const locked=state.busy||state.loading;
  document.body.classList.toggle('is-busy',locked);
  for(const button of document.querySelectorAll('button:not([data-monthly-owned])'))button.disabled=locked;
  monthly?.sync(locked);
  $('site-select').disabled=locked;$('context-date').disabled=locked;$('plan-select').disabled=locked||!state.plans.length;
  const contextLoading=state.sections.context.status==='loading';
  $('plan-fields').disabled=locked||!state.context||contextLoading;
  $('plan-fields').hidden=!state.context;
  const actualReady=['success','empty'].includes(state.sections.actual.status);
  $('actual-fields').disabled=locked||!state.plan?.saved||!actualReady||Boolean(state.record&&!state.correcting);
  $('correct-actual').disabled=locked||!actualReady||!state.plan?.saved;
  $('ack-button').disabled=locked||!state.plan?.saved||state.sections.plan.status==='loading';
  $('replan-button').disabled=locked||!state.plan?.saved||state.sections.plan.status==='loading'||!eventReady(true);
  const waitingForEvents=!monthly&&events('events').length>0&&!eventReady();
  $('plan-button').disabled=locked||!state.context||contextLoading||waitingForEvents;
  $('event-gate').hidden=!waitingForEvents;
  $('preview-create-events').disabled=locked||!state.context||!events('events').length;
  $('edit-inputs').disabled=locked||!state.context;
  $('new-inputs').disabled=locked||!state.selection||contextLoading;
  $('refresh-plans').disabled=locked||!state.selection;
  $('refresh-actual').disabled=locked||!state.selection;
  for(const button of document.querySelectorAll('[data-retry]'))button.disabled=locked||state.sections[button.dataset.retry]?.status==='loading';
  $('correct-actual').hidden=!state.record||state.correcting;
  $('correction-fields').hidden=!state.correcting;$('cancel-correction').hidden=!state.correcting;
  $('correction-reason').required=state.correcting;
  text('actual-button',state.correcting?'정정 내용 저장':'운영 결과 저장');
  text('actual-form-title',state.correcting?'운영 결과 정정':state.record?'저장된 입력값':'현장에서 측정한 값');
}
async function perform(id,message,fn){
  if(state.busy||state.loading)return;
  state.busy=true;syncActions();status(id,message);
  try{await fn();}
  catch(error){status(id,error.message,true);if(error.uncertain&&id==='actual-status'){state.sections.actual={status:'error',error:'저장 여부를 기록 새로고침으로 확인하세요.',retained:!!state.record};renderSections();}}
  finally{state.busy=false;syncActions();}
}
function orderRows(){return [...$('order-rows').children].map(row=>{
  const get=name=>row.querySelector(`[name="${name}"]`).value;
  return {ingredient:get('ingredient').trim(),planned_order:get('planned_order')===''?null:Number(get('planned_order')),unit:get('unit'),...(get('arrival_date')?{arrival_date:get('arrival_date')}:{})};
});}
function addOrder(value={}){
  const row=node('div',null,'order-row');
  for(const [name,label,type] of [['ingredient','식재료','text'],['planned_order','수량','number'],['unit','단위','select'],['arrival_date','입고 예정일','date']]){
    const l=node('label',label),input=node(type==='select'?'select':'input');input.name=name;
    if(type==='select')for(const unit of ['kg','g'])input.append(new Option(unit,unit));else input.type=type;
    input.value=value[name]??(type==='select'?'kg':'');input.required=name!=='arrival_date';
    if(type==='number'){input.min='0';input.max='100000000';input.step='any';}
    if(name==='ingredient')input.maxLength=120;l.append(input);row.append(l);
  }
  const remove=node('button','삭제','secondary small');remove.type='button';remove.setAttribute('aria-label',value.ingredient?`${value.ingredient} 발주 삭제`:'발주 항목 삭제');remove.addEventListener('click',()=>{row.remove();inputChanged();});row.append(remove);$('order-rows').append(row);
}
function planInput(){
  const c=state.context;const attendance={...c.attendance};for(const field of staff)attendance[field]=Number($(field).value);
  return {site_id:c.site_id,target_date:c.target_date,base_request_id:c.base_request_id,
    attendance,weekly_menu:clone(c.weekly_menu),inventory:clone(c.inventory),planned_orders:orderRows(),events:events('events'),menu_uploaded:c.menu_uploaded,inventory_uploaded:c.inventory_uploaded};
}
function formActual(){const result={};for(const field of actualNumbers)result[field]=$(field).value;result.shortage=$('shortage').value;result.notes=$('notes').value;return result;}
function stash(){if(!state.context||state.loading)return;drafts.set(key(),{plan:planInput(),actual:state.record?null:formActual()});}
function setActualFields(record){for(const field of actualNumbers)$(field).value=record?.[field]??'';$('shortage').value=record?.shortage==null?'':String(Boolean(record.shortage));$('notes').value=record?.notes||'';}
function fillContext(context,draft){
  if(draft?.plan){for(const field of ['attendance','weekly_menu','inventory','planned_orders','events','menu_uploaded','inventory_uploaded'])context[field]=clone(draft.plan[field]);}
  state.context=context;
  for(const field of staff)$(field).value=context.attendance[field];
  $('events').value=context.events.filter(x=>typeof x==='string').join('\n');
  $('order-rows').replaceChildren();context.planned_orders.forEach(addOrder);$('orders-details').open=false;
  $('menu-file').value='';$('inventory-file').value='';
  state.createPreview=null;$('create-event-preview').replaceChildren();renderInputs(context);
  text('mode-badge',context.is_demo?'시연 데이터':'운영 데이터');
  for(const id of ['menu-status','inventory-status','create-status','replan-status'])status(id,'');
  $('input-changes').hidden=true;
}
function updateActualContext(){
  if(!state.selection)return;
  text('actual-title',`${state.selection.date.slice(5,7)}월 ${state.selection.date.slice(8)}일 운영 결과`);
  text('actual-context',`${state.context?.site_name||$('site-select').selectedOptions[0]?.textContent||''} · ${state.selection.date} · 점심`);
  const root=$('actual-plan-context');root.replaceChildren();
  if(state.record){
    const matching=state.plans.find(p=>p.id===state.record.plan_request_id);
    root.append(node('strong',matching?`저장 기록의 연결 계획 · 버전 ${matching.version}`:'저장 기록의 기존 비교 기준'));
    if(state.record.plan_request_id&&state.record.plan_request_id!==state.plan?.id)root.append(node('p','현재 선택한 플래너 버전과 다른 기록입니다. 아래 비교는 저장 당시 연결한 계획을 유지합니다.'));
  }else if(state.plan?.saved)root.append(node('strong',`연결 계획 · 버전 ${state.plan.version||'신규'} / 모델 예측 ${fmt(state.plan.model_diners)}명 / 운영 기준 ${fmt(state.plan.operating_diners)}명`));
  else{root.append(node('p','운영 결과를 입력하려면 저장된 계획을 먼저 선택하거나 생성하세요.'));const link=node('a','운영 계획으로');link.href='#/planner';link.dataset.route='planner';root.append(link);}
}
function renderPlanOptions(){
  $('plan-select').replaceChildren();
  if(!state.plans.length)$('plan-select').append(new Option('저장된 계획 없음',''));
  for(const p of state.plans)$('plan-select').append(new Option(`버전 ${p.version} · ${stamp(p.created_at)}${p.saved?'':' · 저장 미완료'}`,p.id));
  $('plan-select').value=state.plan?.id||'';
}
function showScreen(screen,focus=true){
  state.screen=['create','planner','actual'].includes(screen)?screen:'create';
  for(const name of ['create','planner','actual']){$(name+'-screen').hidden=state.screen!==name;if(state.screen===name)$('nav-'+name).setAttribute('aria-current','page');else $('nav-'+name).removeAttribute('aria-current');}
  if(focus){$(state.screen+'-title').focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
}
function address(replace=false){
  if(!state.selection)return;
  const params=new URLSearchParams({site:state.selection.site,date:state.selection.date});if(state.selection.plan)params.set('plan',state.selection.plan);
  const hash=`#/${state.screen}?${params}`;
  if(location.hash!==hash)history[replace?'replaceState':'pushState'](null,'',hash);
  try{localStorage.setItem('lastplate.selection.v2',JSON.stringify({...state.selection,screen:state.screen}));}catch{}
  for(const route of ['create','planner','actual'])$('nav-'+route).href=`#/${route}?${params}`;
}
function route(screen,focus=true){stash();showScreen(screen,focus);address();}
function parsedLocation(){const [screen,query='']=location.hash.replace(/^#\//,'').split('?');const p=new URLSearchParams(query);return {screen:['create','planner','actual'].includes(screen)?screen:'create',site:p.get('site'),date:p.get('date'),plan:p.get('plan')};}
function renderSections(){
  for(const [name,label] of Object.entries(sectionLabels))renderSectionState(name+'-state',state.sections[name],label,name);
  if(state.sections.plan.status==='empty')$('plan-state').hidden=true;
  $('planner-empty').hidden=!!state.plan||state.sections.plan.status!=='empty'||state.sections.plans.status==='error';
  if(!state.plan&&state.sections.plans.status==='error')$('plan-state').hidden=true;
  syncActions();
}
function retained(name){return !!({context:state.context,plan:state.plan,actual:state.record,plans:state.plans.length,history:state.historyRows.length}[name]);}
async function readSection(name,request,apply,empty=()=>false,token=loadVersion){
  const sequence=reads[name]=(reads[name]||0)+1;
  state.sections[name]={status:'loading'};renderSections();
  try{
    const data=await request();
    if(token!==loadVersion||sequence!==reads[name])return {ok:false};
    apply(data);state.sections[name]={status:empty(data)?'empty':'success'};renderSections();return {ok:true,data};
  }catch(error){
    if(token===loadVersion&&sequence===reads[name]){state.sections[name]={status:'error',error:error.message,retained:retained(name)};renderSections();}
    return {ok:false};
  }
}
function restoreActualDraft(){
  const draft=drafts.get(key());
  if(!state.record&&draft?.actual)for(const field of [...actualNumbers,'shortage','notes'])$(field).value=draft.actual[field]??'';
}
const refreshPlans=(token=loadVersion)=>readSection('plans',()=>api.plans(state.selection.site,state.selection.date),data=>{state.plans=data.plans;renderPlanOptions();},data=>!data.plans.length,token);
const refreshContext=(token=loadVersion)=>readSection('context',()=>api.context(state.selection.site,state.selection.date,state.selection.plan),data=>fillContext(data,drafts.get(key())),()=>false,token);
function refreshPlan(token=loadVersion){
  const selection={...state.selection};
  return readSection('plan',()=>selection.plan?api.getPlan(selection.plan):Promise.resolve(null),plan=>{
    if(plan&&(plan.site_id!==selection.site||plan.target_date!==selection.date))throw new Error('이 사업장·날짜의 계획이 아닙니다. 저장 계획을 다시 선택하세요.');
    state.plan=plan;renderPlan(plan);renderPlanOptions();$('replan-events').value=plan?.event_inputs.join('\n')||'';state.preview=null;updateActualContext();
  },plan=>!plan,token);
}
function refreshActual(token=loadVersion){
  return readSection('actual',()=>api.actual(state.selection.site,state.selection.date),result=>{
    state.record=result.record;state.correcting=false;
    // An empty read must not erase an unsaved form.
    if(state.record)setActualFields(state.record);else restoreActualDraft();
    renderActual(state.record);updateActualContext();
  },result=>!result.record,token);
}
const refreshHistory=(token=loadVersion)=>readSection('history',()=>api.history(state.selection.site),data=>{state.historyRows=data.records;renderHistory(data.records);},data=>!data.records.length,token);
async function loadSelection(selection,screen=state.screen,replace=false){
  stash();const same=state.selection&&key()===`${selection.site}|${selection.date}|${selection.plan||''}`;
  const token=++loadVersion;state.loading=true;state.selection={...selection};monthly?.beginSelection();state.correcting=false;invalidateEvents();
  if(!same){state.context=null;state.plan=null;state.record=null;state.plans=[];state.historyRows=[];const sites=state.sections.sites;state.sections={...initialSections(),sites};$('actual-form').reset();renderActual(null);renderHistory([]);renderPlan(null);renderPlanOptions();}
  text('context-status','자료를 불러오는 중…');
  for(const id of ['actual-status','planner-status','create-status','menu-status','inventory-status'])status(id,'');
  $('site-select').value=selection.site;$('context-date').value=selection.date;showScreen(screen,false);syncActions();updateActualContext();
  void refreshActual(token);void refreshHistory(token);
  const list=await refreshPlans(token);
  if(token!==loadVersion)return;
  if(!selection.plan&&!selection.month_day&&list.ok)state.selection.plan=list.data.plans[0]?.id||null;
  state.loading=false;text('context-status','');
  await Promise.allSettled([refreshContext(token),refreshPlan(token)]);
  if(token!==loadVersion)return;
  restoreActualDraft();address(replace);showScreen(state.screen);renderSections();
  await monthly?.onSelection();
}
function acceptPlan(plan,input){
  stash();const token=++loadVersion;state.plan=plan;state.selection.plan=plan.id;state.correcting=false;invalidateEvents();
  if(input)state.context={...state.context,...input,base_request_id:plan.saved?plan.id:input.base_request_id};
  else if(state.context)state.context={...state.context,events:plan.event_inputs,base_request_id:plan.saved?plan.id:state.context.base_request_id};
  if(state.context)fillContext(state.context);
  state.sections.plan={status:'success'};
  renderPlan(plan);$('replan-events').value=plan.event_inputs.join('\n');
  showScreen('planner');address();status('planner-status',plan.saved?'계획을 저장했습니다. 운영 조건과 권고를 검토하세요.':'계산 결과를 유지했습니다. 저장되지 않은 항목은 ‘저장 다시 시도’로 복구하세요.',!plan.saved);
  // Refreshes own their errors; the successful calculation is already usable.
  void refreshPlans(token);
  if(plan.saved)void readSection('context',()=>api.context(state.selection.site,state.selection.date,plan.id),data=>fillContext(data),()=>false,token);
  void refreshActual(token);void refreshHistory(token);updateActualContext();renderSections();
}
function inputChanged(){
  if(!state.context)return;
  const current=planInput(),original=state.context,labels=[];
  for(const [field,label] of [['attendance','근무 현황'],['planned_orders','예정 발주'],['events','변경사항']])if(JSON.stringify(current[field])!==JSON.stringify(original[field]))labels.push(label);
  if(state.context.menu_uploaded)labels.push('업로드 식단');if(state.context.inventory_uploaded)labels.push('업로드 재고');
  $('input-changes').hidden=!state.context.base_request_id||!labels.length;text('input-changes',`새 계획에 반영할 입력: ${labels.join(', ')}. 기존 계획은 보존됩니다.`);stash();
}

document.addEventListener('click',e=>{
  const link=e.target.closest('a[data-route],.main-nav a,.brand');
  if(!link)return;e.preventDefault();if(state.busy||state.loading)return;
  route(link.dataset.route||link.hash.replace('#/','').split('?')[0]);
  if(link.dataset.action==='staff'){$('staff-details').open=true;$('vacation').focus();}
});
$('site-select').addEventListener('change',()=>loadSelection({site:$('site-select').value,date:$('context-date').value,plan:null}));
$('context-date').addEventListener('change',()=>{if($('context-date').value)loadSelection({site:$('site-select').value,date:$('context-date').value,plan:null});});
$('plan-select').addEventListener('change',()=>loadSelection({...state.selection,plan:$('plan-select').value},'planner'));
async function retrySection(name){
  if(state.busy||state.loading)return;
  stash();
  if(name==='sites'){await start();return;}
  const handlers={context:refreshContext,plans:refreshPlans,plan:refreshPlan,actual:refreshActual,history:refreshHistory};
  await handlers[name]?.();
  if(name==='plans'&&!state.selection.plan&&state.plans.length){await loadSelection({...state.selection,plan:state.plans[0].id},state.screen,true);}
}
document.addEventListener('click',e=>{const button=e.target.closest('[data-retry]');if(button)void retrySection(button.dataset.retry);});
$('refresh-plans').addEventListener('click',()=>retrySection('plans'));
$('edit-inputs').addEventListener('click',()=>route('create'));
$('new-inputs').addEventListener('click',()=>perform('create-status','현재 사업장 설정과 등록 자료를 불러옵니다…',async()=>{const context=await api.context(state.selection.site,state.selection.date);drafts.delete(key());fillContext(context);state.sections.context={status:'success'};renderSections();status('create-status','현재 등록 설정과 기본 자료를 불러왔습니다. 일별 입력을 다시 확인하세요. 저장된 계획은 유지됩니다.');}));
$('add-order').addEventListener('click',()=>{addOrder();$('order-rows').lastChild.querySelector('input').focus();inputChanged();});
$('plan-form').addEventListener('input',inputChanged);
$('actual-form').addEventListener('input',stash);
$('events').addEventListener('input',()=>{state.createPreview=null;$('create-event-preview').replaceChildren();syncActions();});
$('replan-events').addEventListener('input',()=>{state.preview=null;$('replan-event-preview').replaceChildren();syncActions();});
for(const [button,input,output,channel,forPlan] of [['preview-create-events','events','create-event-preview','create-status',false],['preview-replan-events','replan-events','replan-event-preview','replan-status',true]]){
  $(button).addEventListener('click',()=>perform(channel,'날짜와 변경 내용을 해석하고 있습니다…',async()=>{
    const confirmedKey=eventKey(forPlan),token=loadVersion;
    const data=await api.preview({site_id:state.selection.site,target_date:state.selection.date,plan_id:forPlan?state.plan.id:null,events:events(input)});
    if(token!==loadVersion||confirmedKey!==eventKey(forPlan))return;
    renderEvents(output,data);state[forPlan?'preview':'createPreview']={key:confirmedKey,data};status(channel,data.needs_review?'내용을 수정한 뒤 다시 확인하세요.':forPlan?'해석한 내용을 확인한 뒤 반영하세요.':'해석한 내용을 확인한 뒤 운영 계획을 생성하세요.',data.needs_review);
  }));
}
$('plan-form').addEventListener('submit',e=>{e.preventDefault();if(monthly){void monthly.generateMonth();return;}perform('create-status','입력 내용을 확인하고 있습니다…',async()=>{
  const input=planInput();
  if(!input.weekly_menu.some(m=>m.date===input.target_date&&m.meal_type==='lunch'))throw new Error('선택한 운영일의 점심 식단이 없습니다. 식단 카드에서 파일을 변경하거나 운영일을 수정하세요.');
  if(input.events.length&&!eventReady())throw new Error('변경사항 해석 확인을 먼저 눌러 날짜와 내용을 확인하세요.');
  $('create-progress').hidden=false;$('create-progress').children[1].classList.add('active');status('create-status','식수·조리량·위험을 계산하고 있습니다. 완료되면 플래너로 이동합니다…');
  try{await acceptPlan(await api.plan(input),input);}finally{$('create-progress').hidden=true;}
});});
$('replan-button').addEventListener('click',()=>perform('replan-status','확인한 변경사항으로 조리량·재료·위험을 다시 계산합니다…',async()=>{
  if(!eventReady(true))throw new Error('변경 내용 확인을 먼저 눌러 주세요.');
  await acceptPlan(await api.replan(state.plan.id,events('replan-events')));status('replan-status','변경 전후 비교가 반영됐습니다.');
}));
$('ack-button').addEventListener('click',()=>perform('planner-status','운영 계획 확인을 기록합니다…',async()=>{if(!state.plan.acknowledged_at){const result=await api.acknowledge(state.plan.id);state.plan.acknowledged_at=result.acknowledged_at;renderPlan(state.plan);}status('planner-status','운영 계획 확인을 기록했습니다. 조리량 확정 상태는 유지됩니다.');route('actual');}));
$('retry-save').addEventListener('click',()=>perform('planner-status','계산을 반복하지 않고 저장을 다시 시도합니다…',async()=>{const saved=await api.retry(state.plan.id);await acceptPlan(saved);await monthly?.onRetried(saved);}));
for(const kind of ['inventory'])$(kind+'-file').addEventListener('change',()=>{
  const file=$(kind+'-file').files[0];if(!file)return;
  perform(kind+'-status','파일 내용과 필수 항목을 확인하고 있습니다…',async()=>{
    let result;try{result=await api.upload(kind,file,state.selection.site,state.selection.date);}finally{$(kind+'-file').value='';}
    state.context[kind==='menu'?'weekly_menu':'inventory']=result.rows;state.context[kind+'_uploaded']=true;
    renderInputs(state.context);inputChanged();monthly?.capture();
    status(kind+'-status',`${kind==='menu'?'식단':'재고'} ${kind==='inventory'?new Set(result.rows.map(r=>r.ingredient)).size:result.row_count}${kind==='menu'?'행':'품목'}을 불러왔습니다. ${result.stored?'자료가 저장됐으며, ':''}새 계획에 반영됩니다.`);
  });
});
$('refresh-actual').addEventListener('click',()=>{if(state.busy||state.loading)return;stash();void refreshActual();void refreshHistory();});
$('actual-form').addEventListener('submit',e=>{e.preventDefault();perform('actual-status',state.correcting?'정정 내용을 저장합니다…':'운영 결과를 저장합니다…',async()=>{
  if(!state.plan?.saved||!['success','empty'].includes(state.sections.actual.status))throw new Error('저장된 계획과 운영 기록을 먼저 확인하세요.');
  const body={site_id:state.selection.site,target_date:state.selection.date,plan_request_id:state.record?.plan_request_id||state.plan.id,shortage:$('shortage').value==='true',notes:$('notes').value};
  for(const field of actualNumbers)body[field]=$(field).value===''?null:Number($(field).value);
  let saved;
  if(state.correcting){body.reason=$('correction-reason').value;body.expected_revision=state.record.revision;saved=await api.correct(body);}else saved=await api.saveActual(body);
  drafts.delete(key());state.record=saved.record;state.sections.actual={status:'success'};state.correcting=false;setActualFields(state.record);renderActual(state.record);updateActualContext();renderSections();
  status('actual-status','운영 결과를 저장했습니다. 저장된 기록으로 비교값을 표시합니다.');
  $('actual-summary').scrollIntoView({block:'start'});void refreshHistory();
});});
$('correct-actual').addEventListener('click',()=>{state.correcting=true;$('correction-reason').value='';syncActions();$('actual_diners').focus();status('actual-status','변경할 값과 정정 사유를 입력하세요.');});
$('cancel-correction').addEventListener('click',()=>{state.correcting=false;setActualFields(state.record);syncActions();status('actual-status','정정을 취소했습니다. 저장된 값은 유지됩니다.');});
$('history').addEventListener('click',e=>{const button=e.target.closest('[data-history-date]');if(button&&!state.busy&&!state.loading)loadSelection({...state.selection,date:button.dataset.historyDate,plan:button.dataset.planId||null},'actual');});
window.addEventListener('popstate',()=>{if(state.busy){address(true);return;}const next=parsedLocation();if(!next.site||!next.date){route(next.screen);return;}loadSelection(next,next.screen,true);});

async function start(){
  state.loading=true;syncActions();
  const result=await readSection('sites',()=>api.sites(),response=>{$('site-select').replaceChildren(...response.sites.map(site=>new Option(site.name,site.id)));if(!response.sites.length)throw new Error('등록된 사업장이 없습니다.');});
  if(result.ok){const response=result.data;
    let selected=parsedLocation();if(!selected.site){try{selected=JSON.parse(localStorage.getItem('lastplate.selection.v2'))||selected;}catch{}}
    if(!response.sites.some(s=>s.id===selected.site))selected.site=response.default_site;
    if(!/^\d{4}-\d{2}-\d{2}$/.test(selected.date||'')){const day=new Date();day.setDate(day.getDate()+1);selected.date=`${day.getFullYear()}-${String(day.getMonth()+1).padStart(2,'0')}-${String(day.getDate()).padStart(2,'0')}`;}
    state.loading=false;await loadSelection(selected,selected.screen||'create',true);
  }else{state.loading=false;syncActions();}
}
monthly=initMonthly({selection:()=>state.selection,plan:()=>state.plan,context:context=>{fillContext(context);state.sections.context={status:'success'};syncActions();},
  present:async(date,plan)=>{await loadSelection({site:state.selection.site,date,plan:null,month_day:true},'planner');acceptPlan(plan);},
  select:(date,plan,screen=state.screen)=>loadSelection({site:state.selection.site,date,plan,month_day:true},screen),input:planInput,locked:()=>state.busy||state.loading,
  run:(label,fn)=>perform(state.screen==='create'?'month-create-status':'month-status',label,fn),showPlanner:()=>route('planner')});
start();
