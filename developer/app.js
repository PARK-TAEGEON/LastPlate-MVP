const $=id=>document.getElementById(id);
const settingsLink=document.createElement('a');settingsLink.href='/admin';settingsLink.textContent='사업장 설정';document.querySelector('.page-heading').append(settingsLink);
const day=new Date();day.setDate(day.getDate()+1);$('day').value=`${day.getFullYear()}-${String(day.getMonth()+1).padStart(2,'0')}-${String(day.getDate()).padStart(2,'0')}`;
async function call(path,options){const r=await fetch('/api'+path,options);const data=await r.json();if(!r.ok)throw new Error(data.message);return data;}
async function run(fn){try{$('status').textContent='처리 중…';await fn();$('status').textContent='완료';}catch(e){$('status').textContent=e.message;}}
$('load').onclick=()=>run(async()=>{const name=$('profile').value,day=$('day').value;const data=await call(`/demo-profile?profile=${name}&target_date=${day}`);const sites={'lh-like':'DEMO-LH','small-site':'DEMO-SMALL','risk-demo':'DEMO-RISK'};data.request.site_id=sites[name];$('request').value=JSON.stringify(data.request,null,2);const link=document.createElement('a');link.textContent='이 사업장의 업무 화면 열기';link.href=`/#/create?site=${sites[name]}&date=${day}`;$('preparation').replaceChildren(link);});
$('run').onclick=()=>run(async()=>{const data=await call('/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:$('request').value});$('identity').value=data.request_id;$('response').textContent=JSON.stringify(data,null,2);});
$('inspect').onclick=()=>run(async()=>{$('response').textContent=JSON.stringify(await call('/plans/'+encodeURIComponent($('identity').value)),null,2);});
$('metrics').onclick=()=>run(async()=>{const request=JSON.parse($('request').value);const site=encodeURIComponent(request.site_id);$('response').textContent=JSON.stringify({kpis:await call('/kpis/'+site),learning:await call('/learning-dataset/'+site)},null,2);});
$('load').click();
