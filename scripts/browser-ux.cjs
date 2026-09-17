/* Real browser, native Agents, actual uploads, SQLite, restart and injected DB failure. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const {randomUUID}=require('node:crypto');
const fs=require('node:fs'),path=require('node:path'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),reports=path.join(root,'reports','ui-minimal');fs.mkdirSync(reports,{recursive:true});
fs.mkdirSync(path.join(root,'work'),{recursive:true});const runDir=fs.mkdtempSync(path.join(root,'work','ux-'));
const steps=[],errors=[],consoleErrors=[],processIds=[];let browser,server,page,serverLog='',enableDeveloper=false;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function stop(){if(!server)return;const child=server;const closed=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Server stop failed')),15000);child.once('exit',()=>{clearTimeout(timer);resolve();});});child.stdin.end('stop\n');await closed;server=null;}
(async()=>{
  const port=await new Promise(resolve=>{const socket=net.createServer();socket.listen(0,'127.0.0.1',()=>{const p=socket.address().port;socket.close(()=>resolve(p));});});
  const url=`http://127.0.0.1:${port}`;
  async function start(){const token=randomUUID();server=spawn(process.env.LASTPLATE_TEST_PYTHON||'python',['scripts/e2e_server.py',String(port)],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',LASTPLATE_DB_PATH:path.join(runDir,'ui.db'),LASTPLATE_MODE:'demo',LASTPLATE_DEBUG:String(enableDeveloper),LASTPLATE_DEBUG_TOKEN:'ux-admin-test-token',LASTPLATE_E2E_TOKEN:token}});server.stdout.on('data',d=>serverLog+=d);server.stderr.on('data',d=>serverLog+=d);server.on('error',e=>errors.push(String(e)));for(let i=0;i<120;i++){try{const identity=await(await fetch(url+'/__e2e_identity')).json();if(identity.token===token){processIds.push(identity.pid);return;}}catch{}await sleep(250);}throw Error('Server startup failed '+serverLog);}
  await start();
  browser=await chromium.launch({headless:true,executablePath:process.env.LASTPLATE_BROWSER_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  page=await browser.newPage({viewport:{width:1440,height:900}});page.setDefaultTimeout(45000);
  page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
  const ready=()=>page.waitForFunction(()=>!document.body.classList.contains('is-busy')&&document.querySelector('#context-status').textContent===''&&!document.querySelector('.section-state[aria-busy="true"]'));
  const shot=name=>page.screenshot({path:path.join(reports,name+'.png'),fullPage:true});
  async function clickResponse(selector,suffix){const response=page.waitForResponse(r=>r.url().endsWith(suffix)&&r.request().method()==='POST');await page.locator(selector).click();const r=await response;assert.equal(r.status(),200,await r.text());return await r.json();}
  await page.goto(url+'/#/create?site=DEMO-LH&date=2026-09-19');await ready();
  assert.equal(await page.locator('.main-nav a').count(),3);assert.equal(await page.locator('pre').count(),0);
  assert.equal(await page.locator('#planned-orders,#advanced,#actual-demo,#site_id').count(),0);
  steps.push('three_business_screens_without_raw_controls');await shot('01-create-desktop');
  const context=await(await fetch(url+'/api/ui/context?site_id=DEMO-LH&target_date=2026-09-19')).json();
  const csv=(rows,keys)=>'\ufeff'+[keys,...rows.map(row=>keys.map(k=>row[k]??''))].map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\n');
  fs.writeFileSync(path.join(runDir,'menu.csv'),csv(context.weekly_menu,['date','meal_type','menu_name']));
  fs.writeFileSync(path.join(runDir,'inventory.csv'),csv(context.inventory,Object.keys(context.inventory[0])));
  await page.locator('#menu-file').setInputFiles(path.join(runDir,'menu.csv'));await page.locator('#menu-status').filter({hasText:'불러왔습니다'}).waitFor();await ready();
  await page.locator('#inventory-file').setInputFiles(path.join(runDir,'inventory.csv'));await page.locator('#inventory-status').filter({hasText:'불러왔습니다'}).waitFor();await ready();
  assert.match(await page.locator('#menu-preview').innerText(),/두부조림/);assert.match(await page.locator('#inventory-preview').innerText(),/품목/);steps.push('real_uploads_and_inline_previews');
  const first=await clickResponse('#plan-button','/api/ui/plan');await ready();await page.locator('#plan-content').waitFor();
  assert.equal(await page.locator('#planner-screen').isVisible(),true);assert.equal(await page.locator('#create-screen').isVisible(),false);
  assert.equal(await page.evaluate(()=>document.activeElement.id),'planner-title');
  assert.match(await page.locator('#plan-summary').innerText(),/미확정/);assert.equal(first.final_servings,null);
  assert.equal(first.model_diners,1111);assert.equal(first.review_servings,1145);
  assert.doesNotMatch(await page.locator('body').innerText(),/SUCCESS|NEEDS_CONFIRMATION|MODEL|IN_RANGE|UNKNOWN|SQLite|request_id|source_payload|[a-f0-9]{32}/);
  steps.push('generated_plan_focus_and_honest_unconfirmed_status');await shot('02-planner-desktop');
  await page.locator('#replan-details summary').click();await page.locator('#replan-events').fill('내일 손님 80명 추가');
  await clickResponse('#preview-replan-events','/api/ui/events/preview');await ready();assert.match(await page.locator('#replan-event-preview').innerText(),/2026-09-19/);
  const second=await clickResponse('#replan-button','/api/ui/replan');await ready();
  assert.equal(second.model_diners,1111);assert.equal(second.operating_diners,1191);assert.equal(second.review_servings,1227);
  await page.locator('#changes-details summary').first().click();assert.match(await page.locator('#plan-changes').innerText(),/\+82/);steps.push('event_date_preview_and_actual_before_after_comparison');
  await clickResponse('#ack-button',`/api/ui/plans/${second.id}/acknowledgement`);await ready();assert.equal(await page.locator('#actual-screen').isVisible(),true);await page.locator('#nav-planner').click();assert.match(await page.locator('#ack-status').innerText(),/열람 기록/);assert.match(await page.locator('#plan-summary').innerText(),/미확정/);
  steps.push('acknowledgement_preserves_unapproved_state');
  await page.locator('#nav-actual').click();assert.equal(await page.locator('#prepared_servings').inputValue(),'');
  await page.locator('#actual_diners').fill('1180');await page.locator('#prepared_servings').fill('1227');await page.locator('#unserved_leftover_kg').fill('3');await page.locator('#plate_waste_kg').fill('2');await page.locator('#shortage').selectOption('false');await page.locator('#notes').fill('UI E2E 검증용 가상 결과');
  const saved=await clickResponse('#actual-button','/api/ui/actual');await ready();assert.equal(saved.record.ingredient_waste_kg,null);
  await page.locator('#actual-summary details').first().locator('summary').click();assert.match(await page.locator('#actual-summary').innerText(),/\+69명/);assert.match(await page.locator('#actual-summary').innerText(),/−11|-11/);assert.match(await page.locator('#actual-summary').innerText(),/미측정/);
  steps.push('exact_plan_link_separate_error_baselines_and_unmeasured_null');
  await page.locator('#correct-actual').click();await page.locator('#actual_diners').fill('1181');await page.locator('#correction-reason').fill('누락된 식수 1명 확인');
  const fixed=await clickResponse('#actual-button','/api/ui/actual/correct');await ready();assert.equal(fixed.record.corrections.length,1);assert.equal(fixed.record.actual_diners,1181);steps.push('audited_actual_correction');await shot('03-actual-desktop');
  await page.locator('#site-select').selectOption('DEMO-SMALL');await ready();
  for(const id of ['actual_diners','prepared_servings','unserved_leftover_kg','plate_waste_kg','ingredient_waste_kg','notes'])assert.equal(await page.locator('#'+id).inputValue(),'');
  assert.doesNotMatch(await page.locator('#actual-summary').innerText(),/1,181|UI E2E/);steps.push('site_change_clears_all_actual_values_notes_summary');
  await page.locator('#nav-create').click();const small=await clickResponse('#plan-button','/api/ui/plan');await ready();assert.equal(small.ood,true);assert.match(await page.locator('#plan-summary').innerText(),/검증되지 않은 예측/);steps.push('ood_warning_and_unclipped_model_visible');
  await page.setViewportSize({width:390,height:844});await shot('04-ood-mobile');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);steps.push('mobile_390px_no_page_overflow');
  await page.locator('#site-select').selectOption('DEMO-RISK');await ready();await page.locator('#nav-create').click();const risk=await clickResponse('#plan-button','/api/ui/plan');await ready();assert.equal(risk.blocked,true);await page.locator('#alternatives-details>summary').click();assert.match(await page.locator('#alternatives-card').innerText(),/사용 불가/);assert.match(await page.locator('#procurement-card').innerText(),/53.6kg/);await shot('05-risk-mobile');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);steps.push('risk_block_and_excluded_candidates_in_business_tables');
  await page.setViewportSize({width:1440,height:900});await page.locator('#site-select').selectOption('DEMO-LH');await ready();
  await page.locator('#plan-select').selectOption(first.id);await ready();await page.locator('#nav-actual').click();assert.match(await page.locator('#actual-plan-context').innerText(),/다른 기록/);await page.locator('#actual-summary details').first().locator('summary').click();assert.match(await page.locator('#actual-summary').innerText(),/-10명/);steps.push('older_plan_selection_does_not_relink_saved_actual');
  await page.locator('#context-date').fill('2026-09-20');await page.locator('#context-date').dispatchEvent('change');await ready();assert.equal(await page.locator('#actual_diners').inputValue(),'');steps.push('date_change_clears_context');
  await page.locator('#history-details>summary').click();await page.locator('#history [data-history-date]').first().click();await ready();assert.equal(await page.locator('#context-date').inputValue(),'2026-09-19');assert.equal(await page.locator('#actual_diners').inputValue(),'1181');
  await page.reload();await ready();assert.equal(await page.locator('#actual_diners').inputValue(),'1181');assert.equal(await page.locator('#plan-select').inputValue(),second.id);steps.push('history_details_url_and_refresh_restore_selected_version');
  await stop();let alive=false;try{await fetch(url+'/api/health');alive=true;}catch{}assert.equal(alive,false);await start();assert.notEqual(processIds[0],processIds[1]);await page.reload();await ready();assert.equal(await page.locator('#actual_diners').inputValue(),'1181');steps.push('real_server_restart_retains_plan_actual_and_correction');
  await page.locator('#nav-create').click();await fetch(url+'/__e2e_fail_next_save',{method:'POST'});
  // No event input: generation remains a single click.
  await page.locator('#events').fill('');const failed=await clickResponse('#plan-button','/api/ui/plan');await ready();assert.equal(failed.saved,false);assert.ok(await page.locator('#retry-save').isVisible());assert.match(await page.locator('#plan-summary').innerText(),/1,111/);
  const retried=await clickResponse('#retry-save',`/api/ui/plans/${failed.id}/retry-save`);await ready();assert.equal(retried.saved,true);assert.equal(retried.id,failed.id);assert.equal(retried.review_servings,failed.review_servings);steps.push('real_database_failure_preserves_calculation_and_retry');
  assert.equal((await fetch(url+'/debug')).status,404);assert.equal((await fetch(url+'/api/plans/'+second.id)).status,404);steps.push('server_enforced_diagnostic_access');
  await page.locator('#nav-planner').focus();await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.id),'nav-actual');await page.keyboard.press('Enter');assert.equal(await page.locator('#actual-screen').isVisible(),true);steps.push('keyboard_navigation_and_current_location');
  // Every fault is injected only into a browser connected to this temporary DB.
  const settle=p=>p.waitForFunction(()=>!document.body.classList.contains('is-busy')&&!document.querySelector('.section-state[aria-busy="true"]'));
  const openPlan=p=>p.goto(url+`/#/planner?site=DEMO-LH&date=2026-09-19&plan=${first.id}`);
  const unavailable=r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'일시적으로 자료를 읽지 못했습니다.'})});
  async function scenario(name,fn){const p=await browser.newPage({viewport:{width:1366,height:768}});p.setDefaultTimeout(25000);p.on('pageerror',e=>errors.push(String(e)));try{await fn(p);steps.push(name);}catch(error){await p.screenshot({path:path.join(reports,'failure-scenario.png'),fullPage:true}).catch(()=>{});throw error;}finally{await p.close();}}
  await scenario('history_failure_does_not_block_plan_or_input_and_retries_locally',async p=>{
    await p.route('**/api/ui/history?**',unavailable);await openPlan(p);await settle(p);
    assert.ok(await p.locator('#plan-content').isVisible());assert.ok(await p.locator('#history-state.error').count());
    await p.locator('#nav-create').click();assert.equal(await p.locator('#plan-button').isEnabled(),true);
    await p.unroute('**/api/ui/history?**');await p.locator('#nav-actual').click();await p.locator('[data-retry="history"]').click();await settle(p);assert.equal(await p.locator('#history-state').isVisible(),false);
  });
  await scenario('actual_read_failure_and_bad_shape_never_become_empty_record',async p=>{
    await p.route('**/api/ui/actual?**',unavailable);await openPlan(p);await settle(p);await p.locator('#nav-actual').click();
    assert.equal(await p.locator('#actual_diners').isDisabled(),true);assert.ok(await p.locator('#actual-state.error').count());
    await p.unroute('**/api/ui/actual?**');await p.route('**/api/ui/actual?**',r=>r.fulfill({json:{unexpected:true}}));
    await p.locator('[data-retry="actual"]').click();await settle(p);assert.match(await p.locator('#actual-state').innerText(),/형식/);assert.equal(await p.locator('#actual_diners').isDisabled(),true);
    await p.unroute('**/api/ui/actual?**');await p.locator('[data-retry="actual"]').click();await settle(p);assert.equal(await p.locator('#actual_diners').inputValue(),'1181');
    await p.route('**/api/ui/actual?**',unavailable);await p.locator('#refresh-actual').click();await settle(p);
    assert.equal(await p.locator('#actual_diners').inputValue(),'1181');assert.match(await p.locator('#actual-state').innerText(),/마지막으로/);assert.equal(await p.locator('#correct-actual').isDisabled(),true);
  });
  for(const [name,pattern] of [['plans','**/api/ui/plans?**'],['context','**/api/ui/context?**'],['plan',`**/api/ui/plans/${first.id}`]]){
    await scenario(`${name}_failure_is_isolated_and_retry_recovers`,async p=>{
      await p.route(pattern,unavailable);await openPlan(p);await settle(p);
      assert.ok(await p.locator(`#${name}-state.error`).count());
      if(name!=='plan')assert.ok(await p.locator('#plan-content').isVisible());
      if(name==='plan')assert.equal(await p.locator('#planner-empty').isVisible(),false);
      if(name==='context')await p.locator('#nav-create').click();
      await p.unroute(pattern);await p.locator(`[data-retry="${name}"]`).click();await settle(p);
      assert.equal(await p.locator(`#${name}-state.error`).count(),0);
    });
  }
  await scenario('site_list_failure_has_working_retry',async p=>{
    await p.route('**/api/ui/sites',unavailable);await openPlan(p);await settle(p);assert.ok(await p.locator('#sites-state.error').count());
    await p.unroute('**/api/ui/sites');await p.locator('[data-retry="sites"]').click();await settle(p);assert.ok(await p.locator('#plan-content').isVisible());
  });
  await scenario('slow_optional_get_times_out_after_15s_without_global_lock',async p=>{
    let release;const held=new Promise(resolve=>release=resolve);
    await p.route('**/api/ui/history?**',async r=>{await held;await r.fulfill({json:{records:[]}}).catch(()=>{});});
    try{await openPlan(p);await p.locator('#plan-content').waitFor();await p.waitForFunction(()=>!document.body.classList.contains('is-busy'));
      await p.locator('#nav-create').click();assert.equal(await p.locator('#plan-button').isEnabled(),true);
      await p.waitForFunction(()=>document.querySelector('#history-state').textContent.includes('초과'),{},{timeout:20000});
      await p.unroute('**/api/ui/history?**');release();await p.locator('#nav-actual').click();await p.locator('[data-retry="history"]').click();await settle(p);
    }finally{release();}
  });
  await scenario('stale_context_response_cannot_replace_new_date',async p=>{
    let release,entered;const held=new Promise(resolve=>release=resolve),seen=new Promise(resolve=>entered=resolve);
    await p.route('**/api/ui/context?**',async r=>{if(new URL(r.request().url()).searchParams.get('target_date')==='2026-09-21'){entered();await held;}await r.continue().catch(()=>{});});
    try{await p.goto(url+'/#/create?site=DEMO-LH&date=2026-09-21');await seen;
      await p.evaluate(()=>{history.pushState(null,'','#/create?site=DEMO-SMALL&date=2026-09-22');dispatchEvent(new PopStateEvent('popstate'));});
      await p.waitForFunction(()=>document.querySelector('#menu-preview').textContent.includes('2026-09-22'));release();await settle(p);
      assert.equal(await p.locator('#site-select').inputValue(),'DEMO-SMALL');assert.match(await p.locator('#staff-summary').innerText(),/600/);assert.match(await p.locator('#menu-preview').innerText(),/2026-09-22/);
    }finally{release();}
  });
  await scenario('event_confirmation_post_failure_ack_and_result_save_with_null_zero',async p=>{
    await p.goto(url+'/#/create?site=DEMO-LH&date=2026-09-21');await settle(p);
    await p.locator('#events').fill('내일 손님 80명 추가');assert.equal(await p.locator('#plan-button').isDisabled(),true);
    await p.locator('#preview-create-events').click();await settle(p);assert.equal(await p.locator('#plan-button').isEnabled(),true);
    await p.locator('#events').fill('알 수 없는 문장');assert.equal(await p.locator('#plan-button').isDisabled(),true);
    await p.locator('#preview-create-events').click();await settle(p);assert.equal(await p.locator('#plan-button').isDisabled(),true);
    await p.locator('#events').fill('내일 손님 80명 추가');await p.locator('#preview-create-events').click();await settle(p);
    await p.locator('#context-date').fill('2026-09-22');await p.locator('#context-date').dispatchEvent('change');await settle(p);
    await p.locator('#events').fill('내일 손님 80명 추가');assert.equal(await p.locator('#plan-button').isDisabled(),true);
    await p.locator('#preview-create-events').click();await settle(p);assert.match(await p.locator('#create-event-preview').innerText(),/2026-09-22/);
    let generationRequests=0;p.on('request',r=>{if(r.url()===url+'/api/ui/plan'&&r.method()==='POST')generationRequests++;});
    await p.route('**/api/ui/plan',unavailable);await p.locator('#plan-button').click();await settle(p);
    assert.equal(generationRequests,1);assert.equal(await p.locator('#events').inputValue(),'내일 손님 80명 추가');assert.ok(await p.locator('#create-status.error').count());
    await p.unroute('**/api/ui/plan');await p.route('**/api/ui/history?**',unavailable);
    const response=p.waitForResponse(r=>r.url()===url+'/api/ui/plan'&&r.request().method()==='POST');await p.locator('#plan-button').click();const created=await(await response).json();await settle(p);
    assert.equal(generationRequests,2);assert.match(await p.locator('#planner-status').innerText(),/저장했습니다/);assert.ok(await p.locator('#history-state.error').count());
    assert.equal(created.operating_diners,created.model_diners+80);
    await p.route('**/acknowledgement',unavailable);await p.locator('#ack-button').click();await settle(p);assert.equal(await p.locator('#planner-screen').isVisible(),true);
    await p.unroute('**/acknowledgement');await p.locator('#ack-button').click();await settle(p);assert.equal(await p.locator('#actual-screen').isVisible(),true);
    await p.locator('#actual_diners').fill('1100');await p.locator('#prepared_servings').fill('1150');await p.locator('#unserved_leftover_kg').fill('0');await p.locator('#shortage').selectOption('false');
    await p.route('**/api/ui/actual',r=>r.abort('failed'));await p.locator('#actual-button').click();await settle(p);
    assert.match(await p.locator('#actual-status').innerText(),/저장 여부/);assert.equal(await p.locator('#actual_diners').inputValue(),'1100');assert.equal(await p.locator('#actual_diners').isDisabled(),true);
    await p.unroute('**/api/ui/actual');await p.locator('[data-retry="actual"]').click();await settle(p);assert.equal(await p.locator('#actual_diners').inputValue(),'1100');
    const actualResponse=p.waitForResponse(r=>r.url()===url+'/api/ui/actual'&&r.request().method()==='POST');await p.locator('#actual-button').click();const actualSaved=await(await actualResponse).json();await settle(p);
    assert.equal(actualSaved.record.unserved_leftover_kg,0);assert.equal(actualSaved.record.plate_waste_kg,null);assert.equal(actualSaved.record.ingredient_waste_kg,null);
    assert.match(await p.locator('#actual-status').innerText(),/저장했습니다/);assert.equal(await p.locator('#actual-status.error').count(),0);
    assert.equal(await p.locator('.result-kpi').count(),3);assert.match(await p.locator('.waste-kpi').innerText(),/0kg/);assert.match(await p.locator('.waste-kpi').innerText(),/미측정/);
    await p.screenshot({path:path.join(reports,'07-partial-history-failure.png'),fullPage:true});
    await p.unroute('**/api/ui/history?**');await p.reload();await settle(p);assert.equal(await p.locator('#actual_diners').inputValue(),'1100');
  });
  await scenario('laptop_layout_sticky_action_and_server_kpi_values',async p=>{
    for(const width of [1366,1440]){await p.setViewportSize({width,height:width===1366?768:900});await openPlan(p);await settle(p);await p.evaluate(()=>scrollTo(0,0));
      assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      const box=await p.locator('#ack-button').boundingBox();assert.ok(box.y>=0&&box.y+box.height<=p.viewportSize().height,'Confirmation remains in viewport');
      assert.match(await p.locator('#plan-summary').innerText(),/1,111/);assert.match(await p.locator('#plan-summary').innerText(),/1,145/);
      await p.screenshot({path:path.join(reports,`08-planner-${width}.png`)});
    }
  });
  await stop();enableDeveloper=true;await start();
  const adminContext=await browser.newContext({httpCredentials:{username:'developer',password:'ux-admin-test-token'}});
  const admin=await adminContext.newPage();admin.on('pageerror',e=>errors.push(String(e)));await admin.goto(url+'/admin');
  await admin.waitForFunction(()=>document.querySelector('#registered_population').value==='3000');
  await admin.locator('#registered_population').fill('3200');await admin.locator('#safety_margin_pct').fill('5');
  const settingsResponse=admin.waitForResponse(r=>r.url().includes('/api/admin/settings/')&&r.request().method()==='PUT');await admin.locator('#save-settings').click();assert.equal((await settingsResponse).status(),200);await admin.locator('#admin-status').filter({hasText:'설정을 저장했습니다'}).waitFor();
  await admin.screenshot({path:path.join(reports,'06-admin-desktop.png'),fullPage:true});
  await page.locator('#nav-create').click();await page.locator('#new-inputs').click();await ready();assert.match(await page.locator('#staff-summary').innerText(),/3,200/);
  const original=await(await fetch(url+'/api/ui/plans/'+first.id)).json();assert.equal(original.margin_pct,3);steps.push('authenticated_admin_settings_apply_only_to_new_context');await adminContext.close();
  assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);
  fs.writeFileSync(path.join(reports,'browser-ux.json'),JSON.stringify({passed:true,steps,errors,consoleErrors,browser:await browser.version(),processIds,verified_at:new Date().toISOString()},null,2));console.log(JSON.stringify({passed:true,steps}));
})().catch(async error=>{console.error(error);if(page)await page.screenshot({path:path.join(reports,'failure.png'),fullPage:true}).catch(()=>{});fs.writeFileSync(path.join(reports,'browser-ux.json'),JSON.stringify({passed:false,steps,errors,consoleErrors,failure:String(error)},null,2));process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();await stop();fs.writeFileSync(path.join(reports,'server.log'),serverLog);});
