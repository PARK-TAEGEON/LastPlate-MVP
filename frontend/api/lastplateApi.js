const base='/api/ui';
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const rows=(value,check=object)=>Array.isArray(value)&&value.every(check);
const context=value=>object(value)&&object(value.attendance)&&['site_id','target_date'].every(k=>typeof value[k]==='string')&&['weekly_menu','inventory','planned_orders'].every(k=>rows(value[k]))&&Array.isArray(value.events);
const plan=value=>object(value)&&typeof value.id==='string'&&typeof value.saved==='boolean'&&object(value.events)&&object(value.sources)&&Array.isArray(value.event_inputs)&&Array.isArray(value.menus)&&['materials','checks','issues'].every(k=>rows(value[k]))&&rows(value.candidates,c=>object(c)&&Array.isArray(c.shortages)&&Array.isArray(c.reasons))&&(!value.changes||rows(value.changes.materials));
const record=value=>object(value)&&typeof value.site_id==='string'&&typeof value.target_date==='string'&&typeof value.actual_diners==='number'&&[true,false,0,1].includes(value.shortage)&&(!value.corrections||rows(value.corrections));
const actual=value=>object(value)&&(value.record===null||record(value.record));
const preview=value=>object(value)&&rows(value.rows)&&typeof value.needs_review==='boolean';
const month=value=>object(value)&&typeof value.month==='string'&&typeof value.revision==='number'&&rows(value.days)&&context(value.context)&&object(value.catalog);
async function request(path,options={},valid=object){
  const reading=!options.method||options.method==='GET';
  const controller=reading?new AbortController():null;
  const timer=controller?setTimeout(()=>controller.abort(),15000):null;
  const uncertain=()=>Object.assign(new Error('응답을 확인하지 못했습니다. 입력은 유지됩니다. 다시 저장하기 전에 저장 계획이나 운영 기록을 새로고침해 저장 여부를 확인하세요.'),{uncertain:true});
  try{
    let response;
    try{response=await fetch(base+path,{cache:'no-store',...options,...(controller?{signal:controller.signal}:{})});}
    catch{throw reading?new Error(controller.signal.aborted?'조회 시간이 초과됐습니다. 다시 시도해 주세요.':'서버에 연결하지 못했습니다. 다시 시도해 주세요.'):uncertain();}
    let data;
    try{data=await response.json();}catch{throw reading?new Error(controller.signal.aborted?'조회 시간이 초과됐습니다. 다시 시도해 주세요.':'응답을 읽지 못했습니다. 다시 시도해 주세요.'):uncertain();}
    if(!response.ok){const error=new Error(typeof data?.message==='string'?data.message:'처리하지 못했습니다. 입력을 확인한 뒤 다시 시도하세요.');error.data=data;throw error;}
    let accepted=false;try{accepted=valid(data);}catch{}
    if(!accepted)throw reading?new Error('자료 형식을 확인하지 못했습니다. 다시 조회해 주세요.'):uncertain();
    return data;
  }finally{if(timer)clearTimeout(timer);}
}
const post=(path,body,valid)=>request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},valid);
const query=params=>new URLSearchParams(Object.entries(params).filter(([,v])=>v!=null&&v!=='')).toString();
export const api={
  confirmDay:(value,day,body)=>post(`/months/${value}/days/${day}/confirm`,body,v=>object(v)&&month(v.month)&&plan(v.plan)),
  dataExamples:(value,day,site_id)=>request(`/months/${value}/days/${day}/data-examples?`+query({site_id}),{},v=>object(v)&&rows(v.providers)&&Array.isArray(v.selected)),
  applyExamples:(value,day,body)=>post(`/months/${value}/days/${day}/data-examples`,body,month),
  month:(site_id,value)=>request(`/months/${encodeURIComponent(value)}?`+query({site_id}),{},month),
  saveMonth:(value,body)=>request(`/months/${encodeURIComponent(value)}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},month),
  saveDay:(value,day,body)=>request(`/months/${encodeURIComponent(value)}/days/${day}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},month),
  generateDay:(value,day,body)=>post(`/months/${encodeURIComponent(value)}/days/${day}/generate`,body,v=>object(v)&&month(v.month)&&plan(v.plan)),
  review:(value,day,body)=>post(`/months/${encodeURIComponent(value)}/days/${day}/review`,body,v=>object(v)&&month(v.month)&&typeof v.needs_recalculation==='boolean'),
  sites:()=>request('/sites',{},v=>object(v)&&typeof v.default_site==='string'&&rows(v.sites,s=>object(s)&&typeof s.id==='string'&&typeof s.name==='string')),
  context:(site_id,target_date,plan_id)=>request('/context?'+query({site_id,target_date,plan_id}),{},context),
  plans:(site_id,target_date)=>request('/plans?'+query({site_id,target_date}),{},v=>object(v)&&rows(v.plans,p=>object(p)&&typeof p.id==='string')),
  getPlan:id=>request('/plans/'+encodeURIComponent(id),{},plan),
  plan:body=>post('/plan',body,plan),
  preview:body=>post('/events/preview',body,preview),
  replan:(id,events)=>post('/replan',{existing_context:id,events},plan),
  acknowledge:id=>post(`/plans/${encodeURIComponent(id)}/acknowledgement`,{},v=>object(v)&&typeof v.acknowledged_at==='string'),
  retry:id=>post(`/plans/${encodeURIComponent(id)}/retry-save`,{},plan),
  actual:(site_id,target_date)=>request('/actual?'+query({site_id,target_date}),{},actual),
  saveActual:body=>post('/actual',body,v=>actual(v)&&v.record!==null),
  correct:body=>post('/actual/correct',body,v=>actual(v)&&v.record!==null),
  history:site_id=>request('/history?'+query({site_id}),{},v=>object(v)&&rows(v.records,record)),
  upload:(kind,file,site_id,target_date)=>{const form=new FormData();form.append('file',file);form.append('site_id',site_id);form.append('target_date',target_date);return request('/upload/'+kind,{method:'POST',body:form},v=>object(v)&&rows(v.rows));},
};
