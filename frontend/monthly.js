import {api} from './api/lastplateApi.js?v=5';
import {$,node,fmt,table} from './components/cards.js?v=5';

const slots={rice:'밥',soup:'국',main:'메인반찬',side:'사이드반찬'};
export function initMonthly(hooks){
  let data=null,sequence=0,running=false,stop=false,loadedKey='',dirty=false,sharedDraft=null,reading=false;
  const dayDrafts=new Map();
  const draftKey=()=>selection()?.site+'|'+selection()?.date;
  const captureDay=()=>({menus:Object.fromEntries(Object.keys(slots).map(s=>[s,$('day-'+s).value])),change:{reason:$('day-reason').value.trim(),increase:Number($('day-increase').value),decrease:Number($('day-decrease').value),note:$('day-note').value.trim()}});
  const selection=()=>hooks.selection();
  const selectedDay=()=>data?.days.find(d=>d.date===selection()?.date);
  const incomplete=day=>day?.summary?.calculation_complete===false;
  const complete=day=>!!day.plan_id&&!day.pending_plan_id&&day.generated_revision===day.revision&&day.summary?.calculation_complete===true;
  function resultMessage(plan,success){
    if(!plan.calculation_complete)return '일부 계산을 완료하지 못했습니다. 계산된 항목은 보존됩니다. 경고 내용을 확인한 뒤 ‘계산 다시 시도’를 눌러 주세요.';
    return plan.saved?success:'계산은 완료했으나 저장되지 않았습니다. 계산 결과의 저장 다시 시도를 이용하세요.';
  }
  function beginSelection(){sequence++;reading=true;const s=selection();if(loadedKey!==s.site+'|'+s.date.slice(0,7)){data=null;$('month-calendar').replaceChildren(node('p','월간 식단을 불러오는 중…'));$('month-menu-table').replaceChildren();$('month-summary').textContent='';}$('day-workspace').hidden=true;$('agent-review').replaceChildren();sync(true);}
  function message(value,error=false){$('month-status').textContent=value;$('month-status').className='local-status '+(error?'error':'success');$('month-status').setAttribute('role',error?'alert':'status');$('month-create-status').textContent=value;$('month-create-status').className='local-status '+(error?'error':'success');}
  function update(next){data=next;dirty=false;render();}
  function context(){if(data)hooks.context({...structuredClone(data.context),...(sharedDraft||{}),target_date:selection().date,events:[],base_request_id:null});}
  function capture(){if(data){const input=hooks.input();sharedDraft=Object.fromEntries(['attendance','inventory','planned_orders','inventory_uploaded'].map(k=>[k,structuredClone(input[k])]));}}
  function sync(locked){
    for(const b of document.querySelectorAll('.monthly-panel button,.day-workspace button')){b.dataset.monthlyOwned='';b.disabled=locked||running||reading||!data||b.dataset.unavailable==='true';}
    $('month-refresh').disabled=locked||running||reading;
    $('month-input').disabled=locked||running;$('day-edit-fields').disabled=locked||running||reading||!data;
    $('month-stop').disabled=!running;$('month-stop').hidden=!running;
  }
  function render(){
    if(!data)return;
    $('month-input').value=data.month;$('month-title').textContent=`${data.month.slice(0,4)}년 ${Number(data.month.slice(5))}월 운영 계획`;
    const unfinished=data.days.filter(incomplete).length;
    $('month-summary').textContent=`식단 ${data.days.length}일 · 계산 완료 ${data.days.filter(complete).length}일${unfinished?' · 계산 미완료 '+unfinished+'일':''}${dirty?' · 저장 전 변경사항':''}`;
    $('monthly-template').href=`/api/ui/months/${data.month}/template`;
    $('month-menu-table').replaceChildren();table($('month-menu-table'),[['날짜','date'],...Object.entries(slots).map(([key,label])=>[label,d=>d.menus[key]])],data.days,'월간 식단표');
    const grid=$('month-calendar');grid.replaceChildren();
    for(const label of ['월','화','수','목','금','토','일'])grid.append(node('span',label,'weekday'));
    const first=new Date(data.month+'-01T12:00:00');const offset=(first.getDay()+6)%7;
    for(let i=0;i<offset;i++)grid.append(node('div',null,'calendar-blank'));
    const count=new Date(first.getFullYear(),first.getMonth()+1,0).getDate();
    for(let number=1;number<=count;number++){
      const date=`${data.month}-${String(number).padStart(2,'0')}`,day=data.days.find(d=>d.date===date);
      const b=node('button',null,'calendar-day'+(date===selection().date?' selected':''));b.type='button';b.dataset.calendarDate=date;b.dataset.unavailable=String(!day);b.disabled=running||!day;b.setAttribute('aria-pressed',String(date===selection().date));
      b.append(node('strong',String(number),'calendar-number'));
      if(day){
        const stale=day.plan_id&&(dirty||day.generated_revision!==day.revision);
        b.append(node('span',incomplete(day)?'계산 미완료 · 다시 시도':day.pending_plan_id?'계산 완료 · 저장 재시도':stale?'수정 · 재계산 필요':day.plan_id?(day.summary?.blocked?'확인 필요':'계획 생성됨'):'계획 생성 전','calendar-status'+(stale||incomplete(day)?' pending':'')));
        for(const [key,label] of Object.entries(slots))b.append(node('span',`${label} · ${day.menus[key]}`,'calendar-menu'));
        if(day.summary)b.append(node('span',`예상 ${fmt(day.summary.operating_diners)}명`,'calendar-diners'));
        if(day.change.increase||day.change.decrease)b.append(node('span',`증가 ${day.change.increase} · 감소 ${day.change.decrease}명`,'calendar-change'));
        b.setAttribute('aria-label',`${date} ${Object.values(day.menus).join(', ')} 운영 계획 보기`);
      }else b.append(node('span','식단 없음','muted'));
      grid.append(b);
    }
    $('month-generate').disabled=running;$('month-input').disabled=running;$('month-refresh').disabled=running;
    $('month-stop').hidden=!running;$('month-stop').disabled=!running;
    renderDay();renderAgent();sync(hooks.locked());
  }
  function renderDay(){
    const saved=selectedDay();$('day-workspace').hidden=!saved;if(!saved)return;const day={...saved,...dayDrafts.get(draftKey())};
    $('day-title').textContent=`${day.date} · 메뉴와 인원 변경`;
    for(const [key,label] of Object.entries(slots)){
      const select=$('day-'+key);select.replaceChildren(...data.catalog[key].map(name=>new Option(name,name)));select.value=day.menus[key];select.setAttribute('aria-label',label);
    }
    for(const key of ['reason','increase','decrease','note'])$('day-'+key).value=day.change[key]??'';
    $('day-edit-fields').disabled=running;
    $('day-apply').textContent=incomplete(day)?'계산 다시 시도':day.plan_id?'변경사항 반영 · 다시 계산':'이 날짜 운영 계획 생성';
    $('day-plan-link').hidden=!day.plan_id;
    $('day-state').textContent=incomplete(day)?'일부 계산을 완료하지 못했습니다. 입력과 계산된 항목은 보존되어 있습니다. 경고를 확인하고 다시 시도하세요.':day.plan_id?(day.generated_revision===day.revision?'저장된 계획을 확인하고 필요한 내용만 수정하세요.':'입력이 변경되었습니다. 다시 계산하면 운영 계획에 반영됩니다.'):'아직 계산 전입니다. 월 전체 생성 또는 이 날짜 생성을 선택하세요.';
  }
  function reviewButtons(root,kind,index,disabled=false){
    const day=selectedDay(),plan=hooks.plan();
    const prior=day.reviews.find(r=>r.plan_id===plan.id&&r.kind===kind&&r.candidate_index===index);
    if(prior){root.append(node('p',prior.decision==='accept'?'수용 기록됨':'거절 기록됨','muted'));return;}
    const actions=node('div',null,'actions');
    for(const [decision,label] of [['accept',kind==='menu'?'검토안 수용 · 재계산':'사유 수용 · 재계산'],['reject','반영 안함']]){
      const button=node('button',label,decision==='reject'?'secondary small':'small');button.type='button';button.dataset.reviewKind=kind;button.dataset.reviewIndex=String(index);button.dataset.reviewDecision=decision;button.dataset.unavailable=String(decision==='accept'&&disabled);button.disabled=running||(decision==='accept'&&disabled);actions.append(button);
    }root.append(actions);
  }
  function renderAgent(){
    const root=$('agent-review');root.replaceChildren(node('h2','운영 Agent 검토'));
    const day=selectedDay(),plan=hooks.plan();
    if(dirty||dayDrafts.has(draftKey())){root.append(node('p','저장 전 변경사항이 있습니다. 변경사항 반영으로 다시 계산한 뒤 새 권고를 검토하세요.','notice info'));return;}
    if(day&&plan&&day.plan_id===plan.id&&!plan.calculation_complete){root.append(node('p','계산을 완료한 뒤 Agent 권고를 검토할 수 있습니다. 위의 ‘계산 다시 시도’를 눌러 주세요.','notice'));return;}
    if(!day||!plan||day.plan_id!==plan.id||day.generated_revision!==day.revision){root.append(node('p','계획 생성 후 날짜를 클릭하면 Agent의 권고와 근거를 확인할 수 있습니다.','muted'));return;}
    root.append(node('p',plan.outcome,'agent-outcome'),node('p',plan.next_action,'muted'));
    if(day.change.reason)root.append(node('p',`인원 변경 사유 · ${day.change.reason} / 증가 ${day.change.increase}명 · 감소 ${day.change.decrease}명`,'notice info'));
    if(day.change.note){
      const note=node('section',null,'agent-proposal');note.append(node('h3','기타 사유 검토'),node('p',day.change.note));
      const parsed=day.note_review,usable=parsed&&!parsed.needs_review&&parsed.rows.length;
      note.append(node('p',usable?parsed.rows.map(r=>`${r.date} · ${r.label}`).join(' / '):'현재 Agent가 자동 해석할 수 없는 내용입니다. 식재료와 변경 내용을 구체적으로 입력해 주세요.','muted'));
      if(day.note_action==='accept')note.append(node('p','운영 조건에 반영됨','badge'));
      else if(day.note_action==='reject')note.append(node('p','반영하지 않음','muted'));
      else reviewButtons(note,'note',0,!usable);root.append(note);
    }
    let proposals=0;
    plan.candidates.forEach((c,index)=>{
      const slot=Object.keys(slots).find(s=>day.menus[s]===c.original_menu);
      if(!slot||!data.catalog[slot].includes(c.menu))return;
      proposals++;
      const card=node('section',null,'agent-proposal');card.append(node('h3',`${c.original_menu} → ${c.menu}`),node('p',`${c.nutrition} · ${c.inventory} · ${c.cost}`,'muted'));
      if(c.reasons.length)card.append(node('p',c.reasons.join(' · '),'notice'));
      card.append(node('p','수용하면 메뉴 검토안을 변경하고 식수·조리량·재료·위험을 다시 계산합니다.','muted'));reviewButtons(card,'menu',index);root.append(card);
    });
    if(!proposals)root.append(node('p','현재 계획에 제안된 메뉴 변경 권고가 없습니다. 메뉴를 직접 수정하면 Agent가 다시 검토합니다.','muted'));
    if(day.reviews.length){const d=node('details');d.append(node('summary','수용·거절 기록'));for(const r of day.reviews.slice().reverse())d.append(node('p',`${r.summary} · ${r.decision==='accept'?'수용':'거절'}${r.reason?' · '+r.reason:''}`));root.append(d);}
  }
  async function onSelection(force=false){
    const current=selection();if(!current)return;
    const month=current.date.slice(0,7),key=current.site+'|'+month;
    if(!force&&loadedKey===key&&data){reading=false;context();render();return;}
    const token=++sequence;const previousKey=loadedKey;reading=true;loadedKey='';sharedDraft=null;
    if(previousKey!==key){data=null;$('day-workspace').hidden=true;$('agent-review').replaceChildren();$('month-calendar').replaceChildren(node('p','월간 식단을 불러오는 중…'));$('month-menu-table').replaceChildren();$('month-summary').textContent='';}
    sync(hooks.locked());message('월간 식단과 운영 계획을 불러옵니다…');
    try{const response=await api.month(current.site,month);if(token!==sequence||selection().site+'|'+selection().date.slice(0,7)!==key)return;loadedKey=key;update(response);context();message('월간 식단의 날짜를 클릭해 내용을 확인하고 변경사항을 반영하세요.');
      const day=selectedDay();if(day&&current.plan!==day.plan_id)await hooks.select(day.date,day.plan_id);
    }catch(error){if(token===sequence){message(error.message,true);if(!data)$('month-calendar').replaceChildren(node('p','월간 계획을 읽지 못했습니다. 새로고침으로 다시 시도하세요.'));}}
    finally{if(token===sequence){reading=false;sync(hooks.locked());}}
  }
  async function run(label,fn){
    if(running||reading||hooks.locked())return;
    running=true;stop=false;render();
    try{await hooks.run(label,async()=>{render();try{await fn();}catch(error){message(error.message,true);}});}
    finally{running=false;render();}
  }
  async function save(){
    if(!data)throw new Error('월간 식단을 먼저 불러오세요.');
    const input=sharedDraft||hooks.input();
    update(await api.saveMonth(data.month,{site_id:selection().site,expected_revision:data.revision,attendance:input.attendance,inventory:input.inventory,planned_orders:input.planned_orders,inventory_uploaded:input.inventory_uploaded,days:data.days.map(d=>({date:d.date,menus:d.menus,change:d.change,...dayDrafts.get(selection().site+'|'+d.date)}))}));
    for(const d of data.days)dayDrafts.delete(selection().site+'|'+d.date);
  }
  async function generateMonth(){
    await run('월간 운영 계획을 준비합니다…',async()=>{
      await save();hooks.showPlanner();const days=data.days.map(d=>d.date),failures=[];let completed=0,lastPlan=null,unsaved=null;
      for(const date of days){
        if(stop)break;
        const day=data.days.find(d=>d.date===date);message(`${data.month} · ${completed}/${days.length}일 완료 · ${date} 계산 중`);$('month-progress').hidden=false;$('month-progress').max=days.length;$('month-progress').value=completed;
        try{const result=await api.generateDay(data.month,date,{site_id:selection().site,expected_revision:day.revision});update(result.month);lastPlan=result.plan;if(!lastPlan.calculation_complete)failures.push(date+' (계산 미완료 · 다시 시도)');if(!lastPlan.saved){if(lastPlan.calculation_complete)failures.push(date+' (계산 완료 · 저장 미완료)');unsaved={date,plan:lastPlan};}}
        catch(error){failures.push(date+' ('+error.message+')');}
        completed++;$('month-progress').value=completed;
      }
      message(`${stop?'생성을 중지했습니다.':'월간 계획 생성을 마쳤습니다.'} ${completed}/${days.length}일 처리${failures.length?' · 다시 확인할 날짜: '+failures.join(', '):''}. 완료된 날짜는 캘린더에 저장됩니다.`,!!failures.length);
      const chosen=selectedDay()?.plan_id?selectedDay():data.days.find(d=>d.plan_id);if(unsaved)await hooks.present(unsaved.date,unsaved.plan);else if(chosen)await hooks.select(chosen.date,chosen.plan_id);
      $('month-progress').hidden=true;
    });
  }
  $('month-calendar').addEventListener('click',async e=>{const b=e.target.closest('[data-calendar-date]');if(!b||running||hooks.locked())return;const day=data.days.find(d=>d.date===b.dataset.calendarDate);await hooks.select(day.date,day.plan_id,'planner');$('day-workspace').scrollIntoView({block:'start'});});
  $('day-form').addEventListener('input',()=>{dayDrafts.set(draftKey(),captureDay());$('day-reason').required=Number($('day-increase').value)>0||Number($('day-decrease').value)>0;$('day-state').textContent='저장 전 변경사항이 있습니다. 아래 변경사항 반영을 눌러 계산하세요.';renderAgent();sync(hooks.locked());});
  $('plan-form').addEventListener('input',capture);
  $('day-form').addEventListener('submit',e=>{e.preventDefault();const {menus,change}=captureDay();void run('변경사항을 반영하고 Agent가 다시 계산합니다…',async()=>{
    if(!data.revision)await save();const day=selectedDay();
    update(await api.saveDay(data.month,day.date,{site_id:selection().site,expected_revision:day.revision,menus,change}));
    dayDrafts.delete(draftKey());
    const fresh=selectedDay();const result=await api.generateDay(data.month,fresh.date,{site_id:selection().site,expected_revision:fresh.revision});update(result.month);if(result.plan.saved)await hooks.select(fresh.date,result.plan.id);else await hooks.present(fresh.date,result.plan);message(resultMessage(result.plan,'선택한 날짜의 변경사항을 반영했습니다. Agent 권고를 확인하세요.'),!result.plan.saved||!result.plan.calculation_complete);
  });});
  $('agent-review').addEventListener('click',e=>{const b=e.target.closest('[data-review-kind]');if(!b)return;void run('권고 선택을 기록합니다…',async()=>{
    const day=selectedDay();const response=await api.review(data.month,day.date,{site_id:selection().site,expected_revision:day.revision,plan_id:hooks.plan().id,kind:b.dataset.reviewKind,candidate_index:Number(b.dataset.reviewIndex),decision:b.dataset.reviewDecision,reason:''});update(response.month);
    if(response.needs_recalculation){message('수용한 검토안으로 Agent가 다시 계산합니다…');const fresh=selectedDay();const result=await api.generateDay(data.month,fresh.date,{site_id:selection().site,expected_revision:fresh.revision});update(result.month);if(!result.plan.saved){await hooks.present(fresh.date,result.plan);message(resultMessage(result.plan,''),true);return;}await hooks.select(fresh.date,result.plan.id);if(!result.plan.calculation_complete){message(resultMessage(result.plan,''),true);return;}}
    message(response.needs_recalculation?'수용한 내용을 재계산했습니다. 새 계획의 경고와 권고를 확인하세요.':'반영하지 않기로 기록했습니다. 기존 메뉴는 유지됩니다.');
  });});
  $('menu-file').addEventListener('change',()=>{const file=$('menu-file').files[0];if(!file)return;void run('월간 식단표를 확인합니다…',async()=>{
    let result;try{result=await api.upload('monthly-menu',file,selection().site,selection().date);}finally{$('menu-file').value='';}
    if(result.rows.some(r=>r.date.slice(0,7)!==data.month))throw new Error('선택한 운영 월의 식단만 올려주세요.');
    for(const row of result.rows)for(const slot of Object.keys(slots))if(!data.catalog[slot].includes(row[slot]))throw new Error(`${row.date} · ${row[slot]}: 등록된 ${slots[slot]} 메뉴명을 사용해 주세요. 양식의 메뉴를 참고하세요.`);
    const previous=new Map(data.days.map(d=>[d.date,d]));
    data.days=result.rows.map(row=>{const prior=previous.get(row.date);const change=dayDrafts.get(selection().site+'|'+row.date)?.change||prior?.change||{reason:'',increase:0,decrease:0,note:''};dayDrafts.delete(selection().site+'|'+row.date);return {...(prior||{revision:1,plan_id:null,generated_revision:null,reviews:[]}),date:row.date,menus:Object.fromEntries(Object.keys(slots).map(s=>[s,row[s]])),change};});dirty=true;
    data.context.weekly_menu=data.days.flatMap(d=>Object.values(d.menus).map(menu_name=>({date:d.date,meal_type:'lunch',menu_name})));render();message(`${data.days.length}일 식단을 불러왔습니다. 월간 운영 계획 생성으로 저장·계산하세요.`);
  });});
  $('month-generate').addEventListener('click',()=>void generateMonth());$('month-stop').addEventListener('click',()=>{stop=true;message('현재 날짜 계산 후 중지합니다. 이미 생성한 계획은 보존됩니다.');});
  $('month-refresh').addEventListener('click',()=>{if(!running&&!hooks.locked())void onSelection(true);});
  $('month-input').addEventListener('change',()=>{if($('month-input').value)void hooks.select($('month-input').value+'-01',null);});
  $('day-plan-link').addEventListener('click',()=>$('plan-summary').scrollIntoView({block:'start'}));
  async function onRetried(plan){const day=selectedDay();if(day?.pending_plan_id===plan.id){const result=await api.generateDay(data.month,day.date,{site_id:selection().site,expected_revision:day.revision});update(result.month);}}
  return {beginSelection,onSelection,generateMonth,renderAgent,sync,capture,onRetried};
}
