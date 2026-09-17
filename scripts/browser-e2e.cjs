/* Real browser + real HTTP server + native model + durable SQLite. No API mocks. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const {randomUUID}=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const net=require('node:net');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const reportDir=path.join(root,'reports');
fs.mkdirSync(path.join(root,'work'),{recursive:true});
const runDir=fs.mkdtempSync(path.join(root,'work','browser-'));
let server,browser;
const errors=[],consoleErrors=[],steps=[];
const processIds=[];
let serverLog='';
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

async function stop(){
  if(!server)return;
  const child=server;
  const exited=new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('Test server did not shut down')),15000);
    child.once('exit',()=>{clearTimeout(timer);resolve();});
  });
  child.stdin.end('stop\n');
  await exited;server=null;
}

(async()=>{
  const port=await new Promise(resolve=>{const socket=net.createServer();socket.listen(0,'127.0.0.1',()=>{const p=socket.address().port;socket.close(()=>resolve(p));});});
  const url=`http://127.0.0.1:${port}`;
  async function start(){
    const token=randomUUID();
    server=spawn(process.env.LASTPLATE_TEST_PYTHON||'python',['scripts/e2e_server.py',String(port)],{cwd:root,windowsHide:true,
      env:{...process.env,PYTHONUTF8:'1',LASTPLATE_E2E_TOKEN:token,LASTPLATE_DB_PATH:path.join(runDir,'lastplate.db'),LASTPLATE_MODE:'demo'}});
    server.stdout.on('data',d=>serverLog+=d);server.stderr.on('data',d=>serverLog+=d);
    server.on('error',e=>errors.push(String(e)));
    for(let i=0;i<120;i++){
      try{const identity=await(await fetch(url+'/__e2e_identity')).json();
        if(identity.token===token){processIds.push(identity.pid);return;}}catch{}
      await sleep(250);
    }
    throw Error('Server startup failed: '+serverLog);
  }
  await start();
  const sample=await(await fetch(url+'/api/demo-profile')).json();
  const csv=(rows,keys)=>'\ufeff'+[keys,...rows.map(r=>keys.map(k=>r[k]??''))].map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\n');
  const menuPath=path.join(runDir,'menu.csv');
  const inventoryPath=path.join(runDir,'inventory.csv');
  fs.writeFileSync(menuPath,csv(sample.request.weekly_menu,['date','meal_type','menu_name']));
  fs.writeFileSync(inventoryPath,csv(sample.request.inventory,Object.keys(sample.request.inventory[0])));
  const edge='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const executable=process.env.LASTPLATE_BROWSER_PATH||(fs.existsSync(edge)?edge:undefined);
  browser=await chromium.launch({headless:true,...(executable?{executablePath:executable}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  page.setDefaultTimeout(120000);
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
  await page.goto(url);await page.locator('#site_id').waitFor();
  await page.waitForFunction(()=>document.querySelector('#site_id').value==='DEMO-LH');
  steps.push('app_loaded');
  await page.locator('#site_name').fill('브라우저 E2E 시연 사업장');
  steps.push('site_entered');
  await page.locator('#menu-file').setInputFiles(menuPath);
  await page.locator('#menu-upload-status').filter({hasText:'USER_UPLOAD'}).waitFor();
  await page.locator('#inventory-file').setInputFiles(inventoryPath);
  await page.locator('#inventory-upload-status').filter({hasText:'SQLite 저장 완료'}).waitFor();
  steps.push('menu_and_inventory_uploaded');
  const firstResponse=page.waitForResponse(r=>r.url().endsWith('/api/plan')&&r.request().method()==='POST');
  await page.locator('#plan-button').click();const initial=await(await firstResponse).json();
  assert.equal(initial.pipeline_status,'SUCCESS');
  await page.locator('#pipeline-status').filter({hasText:'SUCCESS'}).waitFor();
  for(const id of ['demand-card','operation-card','risk-card','decision-card'])assert.ok(await page.locator('#'+id).isVisible());
  assert.match(await page.locator('#demand-card .big-number').innerText(),new RegExp(initial.demand.predicted_diners.toLocaleString('ko-KR')));
  steps.push('plan_generated_and_four_agent_results_displayed');
  await page.screenshot({path:path.join(reportDir,'browser-plan.png'),fullPage:true});
  await page.locator('#events').fill('내일 손님 80명 추가');
  const replanResponse=page.waitForResponse(r=>r.url().endsWith('/api/replan'));
  await page.locator('#replan-button').click();const replanned=await(await replanResponse).json();
  assert.equal(replanned.demand.predicted_diners,initial.demand.predicted_diners);
  assert.equal(replanned.operation.base_demand,initial.operation.base_demand+80);
  assert.ok(replanned.operation.recommended_servings>initial.operation.recommended_servings);
  await page.waitForFunction(id=>document.querySelector('#request-label').textContent===id,replanned.request_id);
  steps.push('event_replanned_and_model_raw_preserved');
  await page.locator('#ack-button').click();
  await page.locator('#ack-status').filter({hasText:'발주·메뉴 변경은 실행되지 않습니다'}).waitFor();
  steps.push('read_acknowledgement_without_approval');
  await page.locator('#tab-actual').click();
  await page.locator('#actual_diners').fill('1100');await page.locator('#prepared_servings').fill('1300');
  await page.locator('#unserved_leftover_kg').fill('18.4');await page.locator('#plate_waste_kg').fill('31.2');
  await page.locator('#ingredient_waste_kg').fill('3.1');await page.locator('#notes').fill('브라우저 실측 입력 시연');
  const actualResponse=page.waitForResponse(r=>r.url().endsWith('/api/actual-results'));
  await page.locator('#actual-button').click();const saved=await(await actualResponse).json();
  assert.equal(saved.saved,true);assert.equal(saved.summary.overprep_servings,200);
  await page.locator('#status').filter({hasText:'저장 완료'}).waitFor();
  assert.match(await page.locator('#actual-summary').innerText(),/절대 예측 오차/);
  assert.match(await page.locator('#history').innerText(),/1,100/);
  steps.push('actual_entered_saved_and_history_displayed');
  await page.screenshot({path:path.join(reportDir,'browser-actual.png'),fullPage:true});
  await stop();
  let stillAlive=false;try{await fetch(url+'/api/health');stillAlive=true;}catch{}
  assert.equal(stillAlive,false,'Old HTTP server must actually stop');
  await start();assert.notEqual(processIds[0],processIds[1]);
  const history=await(await fetch(url+'/api/history/DEMO-LH')).json();
  assert.equal(history.records[0].result_id,saved.result.result_id);
  assert.equal(history.records[0].prediction_id,replanned.demand.prediction_id);
  steps.push('process_restart_preserved_sqlite_data');
  await page.reload();await page.waitForFunction(()=>document.querySelector('#site_id').value==='DEMO-LH');
  await page.locator('#registered_population').fill('600');
  const oodResponse=page.waitForResponse(r=>r.url().endsWith('/api/plan')&&r.request().method()==='POST');
  await page.locator('#plan-button').click();const ood=await(await oodResponse).json();
  assert.equal(ood.demand.applicability,'OUT_OF_DISTRIBUTION');
  await page.locator('.ood-warning').waitFor();steps.push('ood_visible_in_browser');
  await page.screenshot({path:path.join(reportDir,'browser-ood.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);
  fs.writeFileSync(path.join(reportDir,'browser-e2e.json'),JSON.stringify({passed:true,steps,errors,consoleErrors,
    browser:await browser.version(),processIds,initial:{prediction:initial.demand.predicted_diners,servings:initial.operation.recommended_servings},
    replan:{prediction:replanned.demand.predicted_diners,servings:replanned.operation.recommended_servings},
    saved_result_id:saved.result.result_id,verified_at:new Date().toISOString()},null,2));
  console.log(JSON.stringify({passed:true,steps,errors,consoleErrors}));
})().catch(e=>{
  console.error(e);fs.writeFileSync(path.join(reportDir,'browser-e2e.json'),JSON.stringify({passed:false,steps,errors,consoleErrors,failure:String(e)},null,2));process.exitCode=1;
}).finally(async()=>{if(browser)await browser.close();await stop();fs.writeFileSync(path.join(reportDir,'browser-server.log'),serverLog);});
