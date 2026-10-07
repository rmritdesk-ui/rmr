const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../public/pages/billing.js'), 'utf8')
  .replace(/^import[\s\S]*?;\s*/gm, '').replace('export async function', 'async function');

function context(api, available=false) {
  const storage=new Map(), page={innerHTML:''};
  const button={disabled:false,addEventListener(_,fn){this.click=fn;}};
  const box={textContent:''};
  const data={tenant:{id:'tenant'},setup_status:'ready',can_manage:true,
    payment_method:{brand:'visa',last4:'4242'},sandbox_test_charge_available:available};
  const c={URLSearchParams, URL, api:api || (async()=>data),state:{selectedTenantId:'tenant'},
    window:{location:{search:''},confirm:()=>true},
    sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
    $:selector=>selector==='#page'?page:selector==='#billing-test-charge-result'?box:
      selector==='#billing-test-charge' && page.innerHTML.includes('id="billing-test-charge"')?button:null,
    syncBillingNavigation(data){c.state.billingLocked=!!data.monthly?.billing_required;},
    setActiveNav(){},loading:()=>'',pageHead:()=>'',esc:String,badge:()=>'',toast(){},empty:()=>''};
  vm.createContext(c);vm.runInContext(source,c);
  return {c,page,button,box,storage,data};
}

test('live/unavailable billing never renders sandbox action',async()=>{
  const {c,page}=context();await c.renderBillingPage();
  assert.ok(page.innerHTML.includes('Secure billing'));
  assert.ok(!page.innerHTML.includes('id="billing-test-charge"'));
});
test('timeout does not advance logical operation; success advances explicitly',async()=>{
  const calls=[];let fail=true;
  const {c,storage}=context(async(url,options)=>{
    calls.push([url,options.body]);
    if(url.includes('/operations/'))return {operation_id:'op_retry'};
    if(fail)throw Error('timeout');return {status:'succeeded'};
  });
  await assert.rejects(c.runBillingOperation('tenant','setup','setup-intent'));
  assert.equal(storage.size,0);fail=false;
  await c.runBillingOperation('tenant','setup','setup-intent');
  assert.equal(calls[0][1].previous_operation_id,null);
  assert.equal(calls[2][1].previous_operation_id,null);
  assert.equal(calls[1][1].operation_id,calls[3][1].operation_id);
  assert.equal(storage.get('rmr-billing-completed:tenant:setup'),'op_retry');
});
test('normal browser completion still calls complete endpoint',async()=>{
  let captured;
  const {c}=context(async(url,options)=>{captured={url,options};return {ok:true};});
  await c.completeSetupIntent('tenant','seti_test');
  assert.equal(captured.url,'/api/tenants/tenant/billing/payment-method/complete');
  assert.equal(captured.options.body.setup_intent_id,'seti_test');
});

function monthlyData(stage='ready_to_activate') {
  return {stage,billing_required:stage!=='active',services:[{name:'ProspectIQ Access',amount_cents:17500}],
    unpriced_services:[{name:'CRM'}],total_cents:17500,quote_hash:'review'};
}

test('Resolve Payment is limited to server-reported actionable state; refresh and $1 feature absent',()=>{
  const {c,data}=context();data.subscription_activation_available=true;
  for(const stage of ['ready_to_activate','active','payment_problem']){
    data.monthly=monthlyData(stage);
    data.monthly.subscription={id:'sub',status:stage==='active'?'active':'canceled',payment_action_required:false,services:[],monthly_amount_cents:17500};
    assert.doesNotMatch(c.monthlyPanel(data),/>Resolve Payment</);
  }
  data.monthly.subscription.payment_action_required=true;
  assert.match(c.monthlyPanel(data),/>Resolve Payment</);
  data.payment_method=null;assert.equal(c.monthlyPanel(data),'');
  assert.doesNotMatch(source,/Refresh Billing Status|Run \$1 Sandbox Test Charge|\/test-charge/);
});

test('monthly panel shows server prices, unpriced services and explicit unchecked consent',()=>{
  const {c,data}=context();data.monthly=monthlyData();data.subscription_activation_available=true;
  const html=c.monthlyPanel(data);
  assert.match(html,/Review your services/);assert.match(html,/\$175.00 USD/);
  assert.match(html,/CRM \(unpriced\)/);assert.match(html,/id="billing-activate-monthly" disabled/);
  assert.match(html,/authorize the monthly charge/);assert.doesNotMatch(html,/checked/);
});

test('active billing separates current itemized agreement from next-cycle pricing',()=>{
  const {c,data}=context();data.monthly=monthlyData('active');
  data.monthly.subscription={services:[{name:'CRM',amount_cents:3000},{name:'Core',amount_cents:4000},{name:'Enhancement',amount_cents:1000}],
    monthly_amount_cents:8000,last_payment_status:'paid',current_period_end:'2026-11-05'};
  data.monthly.next_cycle={total_cents:9000,status:'scheduled',effective_date:'2026-11-05'};
  const html=c.monthlyPanel(data);
  assert.match(html,/Monthly total: \$80.00 USD/);
  assert.match(html,/Next billing cycle: \$90.00\/month/);
  assert.match(html,/Effective date: 2026-11-05/);
  assert.match(html,/Next billing date \/ current period end: 2026-11-05/);
  assert.match(html,/CRM/);assert.match(html,/\$40.00 USD\/month/);
  assert.doesNotMatch(html,/update pending confirmation/);
  data.monthly.next_cycle.status='pending';assert.match(c.monthlyPanel(data),/update pending confirmation/);
});

test('no card and live unavailable states cannot activate; active does not repurchase',()=>{
  const {c,data}=context();data.subscription_activation_available=true;
  for(const stage of ['payment_method_required','payment_problem','active','no_billable_services']) {
    data.monthly=monthlyData(stage);
    assert.ok(!c.monthlyPanel(data).includes('id="billing-activate-monthly"'));
  }
  data.monthly=monthlyData();data.subscription_activation_available=false;
  assert.ok(!c.monthlyPanel(data).includes('id="billing-activate-monthly"'));
});

test('monthly double submit blocked; only operation, confirmation and quote hash sent',async()=>{
  const x=context(), nodes={};x.data.monthly=monthlyData();x.data.subscription_activation_available=true;
  for(const id of ['billing-monthly-consent','billing-activate-monthly','billing-monthly-result'])
    nodes['#'+id]={checked:false,disabled:true,addEventListener(type,fn){this[type]=fn;}};
  const original=x.c.$;x.c.$=s=>nodes[s]||original(s);
  let activations=0, body;
  x.c.api=async(url,opts)=>{
    if(url.endsWith('/billing'))return x.data;
    if(url.includes('/operations/'))return {operation_id:'subscription-op'};
    activations++;body=opts.body;x.data.monthly=monthlyData('active');return {monthly:x.data.monthly};
  };
  await x.c.renderBillingPage();const button=nodes['#billing-activate-monthly'],consent=nodes['#billing-monthly-consent'];
  await button.click();assert.equal(activations,0);
  consent.checked=true;consent.change();assert.equal(button.disabled,false);
  await Promise.all([button.click(),button.click()]);assert.equal(activations,1);
  assert.deepEqual(JSON.parse(JSON.stringify(body)),{confirmed:true,quote_hash:'review',operation_id:'subscription-op'});
  assert.ok(!x.page.innerHTML.includes('id="billing-activate-monthly"'));
});

test('action-required uses Stripe confirmation then authoritative server refresh',async()=>{
  const x=context();let args,refreshes=0;
  x.c.window.Stripe=key=>({confirmCardPayment:async(secret,options)=>{args={key,secret,options};return {paymentIntent:{status:'succeeded'}};}});
  x.c.api=async url=>{assert.match(url,/subscription\/refresh$/);refreshes++;return {monthly:{stage:'active'}};};
  const result=await x.c.finishMonthlyPayment({client_secret:'pi_fixture_secret',publishable_key:'pk_test_fixture',payment_method_id:'pm_saved'},'tenant');
  assert.equal(args.options.payment_method,'pm_saved');assert.equal(refreshes,1);assert.equal(result.monthly.stage,'active');
});

test('payment authentication failure is not represented as active',async()=>{
  const x=context();x.c.window.Stripe=()=>({confirmCardPayment:async()=>({error:{message:'Authentication failed'}})});
  await assert.rejects(x.c.finishMonthlyPayment({client_secret:'fixture',publishable_key:'pk_test'},'tenant'),/Authentication failed/);
});

test('card save refreshes billing review; login redirect and backend-402 redirect are wired',()=>{
  assert.match(source,/await completeSetupIntent\(tenantId, result.setupIntent.id\);[\s\S]*?await renderBillingPage\(ctx\)/);
  const app=fs.readFileSync(path.join(__dirname,'../public/app.js'),'utf8');
  assert.match(app,/if \(state.billingLocked\) navigate\("billing", false\)/);
  assert.match(app,/history.replaceState\(null, "", "#\/billing"\)/);
  assert.match(app,/window.addEventListener\("rmr:billing-required"/);
});

test('no-card screen hides all service review, prices and activation controls',async()=>{
  const x=context();x.data.monthly=monthlyData('payment_method_required');
  x.data.payment_method=null;x.data.setup_status='not_configured';x.data.subscription_activation_available=true;
  await x.c.renderBillingPage();
  assert.match(x.page.innerHTML,/Payment Method Required/);
  assert.match(x.page.innerHTML,/Add Payment Method/);
  for(const absent of ['175.00','ProspectIQ Access','Monthly total','billing-monthly-consent','billing-activate-monthly','subscription confirmation'])
    assert.ok(!x.page.innerHTML.includes(absent),absent);
  assert.equal(x.c.state.billingLocked,true);
  x.data.setup_status='ready';x.data.payment_method={brand:'visa',last4:'4242'};x.data.monthly=monthlyData();
  await x.c.renderBillingPage();assert.match(x.page.innerHTML,/175.00/);assert.match(x.page.innerHTML,/CRM \(unpriced\)/);
  assert.equal(x.c.state.billingLocked,true);
  x.data.monthly=monthlyData('active');await x.c.renderBillingPage();assert.equal(x.c.state.billingLocked,false);
});

test('sidebar locks all modules except Billing; paid and global admin unlock',()=>{
  const ui=fs.readFileSync(path.join(__dirname,'../public/ui.js'),'utf8');
  const fn=ui.slice(ui.indexOf('export function syncBillingNavigation'),ui.indexOf('export function renderShell')).replace('export ','');
  const buttons=['home','crm','piq','reports','training','solutions','organization','email','billing'].map(nav=>({dataset:{nav},setAttribute(){}}));
  let admin=false;const c={state:{},isGlobalAdmin:()=>admin,$$:()=>buttons};vm.createContext(c);vm.runInContext(fn,c);
  c.syncBillingNavigation({monthly:{billing_required:true}});
  assert.ok(buttons.slice(0,-1).every(b=>b.disabled && b.title==='Complete billing setup to unlock'));
  assert.equal(buttons.at(-1).disabled,false);
  c.syncBillingNavigation({monthly:{billing_required:false}});assert.ok(buttons.every(b=>!b.disabled));
  admin=true;c.syncBillingNavigation({monthly:{billing_required:true}});assert.ok(buttons.every(b=>!b.disabled));
});

test('direct hash route redirects before rendering any protected module',async()=>{
  const app=fs.readFileSync(path.join(__dirname,'../public/app.js'),'utf8');
  const fn=app.slice(app.indexOf('async function renderRoute()'),app.indexOf('async function enterClientWorkspace'));
  let billing=0,hash;
  const c={state:{user:{},selectedTenantId:'tenant'},isGlobalAdmin:()=>false,parseHash:()=>({route:'crm'}),
    api:async()=>({monthly:{billing_required:true}}),syncBillingNavigation:()=>{c.state.billingLocked=true;},
    history:{replaceState:(_,__,h)=>{hash=h;}},renderBillingPage:()=>{billing++;}};
  vm.createContext(c);vm.runInContext(fn,c);await c.renderRoute();
  assert.equal(hash,'#/billing');assert.equal(billing,1);
});

test('Client Pricing renders and saves an assigned monthly price using existing admin API',async()=>{
  const admin=fs.readFileSync(path.join(__dirname,'../public/pages/admin.js'),'utf8');
  const code=admin.slice(admin.indexOf('async function pricing('),admin.indexOf('async function addServiceModal('));
  const service={catalog:{name:'ProspectIQ Access',standard_price_cents:17500},
    tenant_service:{id:'assignment',contract_price_cents:10000,cadence:'monthly',status:'active'}};
  const page={innerHTML:'',insertAdjacentHTML(_,html){this.innerHTML+=html;},querySelector(){return input;}};
  const input={value:'20.00',reportValidity:()=>true};
  const button={dataset:{saveMonthlyPrice:'assignment'},addEventListener(_,fn){this.click=fn;}};
  let saved;
  const c={selectedTenant:()=>({id:'tenant',name:'Client A'}),state:{},esc:String,money:n=>`$${n/100}`,
    pageHead:()=>'',acronym:String,badge:String,statusTone:String,toast(){},$:()=>null,
    $$:selector=>selector==='[data-save-monthly-price]'?[button]:[],
    api:async(url,opts)=>{
      if(opts?.method==='PATCH'){saved={url,body:opts.body};service.tenant_service.contract_price_cents=opts.body.contract_price_cents;return {};}
      return url.includes('/summary')?{tenants:[]}:{services:[service]};
    }};
  vm.createContext(c);vm.runInContext(code,c);await c.pricing(page,{});
  assert.match(page.innerHTML,/Monthly Price \(USD\)/);assert.match(page.innerHTML,/value="100"/);
  assert.match(page.innerHTML,/next billing cycle without proration/);
  await button.click();assert.equal(saved.url,'/api/tenant-services/assignment');assert.equal(saved.body.contract_price_cents,2000);
  assert.match(page.innerHTML,/value="20"/);
});

test('late tenant A response cannot overwrite fresh tenant B billing',async()=>{
  const x=context();let finishA;
  x.c.api=async(url)=>url.includes('/tenant/')?new Promise(resolve=>{finishA=resolve;}):
    {tenant:{id:'other'},setup_status:'not_configured',payment_method:null,can_manage:true,monthly:monthlyData('payment_method_required')};
  const pending=x.c.renderBillingPage();await new Promise(resolve=>setImmediate(resolve));
  x.c.state.selectedTenantId='other';await x.c.renderBillingPage();
  finishA(x.data);await pending;
  assert.match(x.page.innerHTML,/Payment Method Required/);assert.doesNotMatch(x.page.innerHTML,/4242/);
});

test('billing rejects a response for another tenant',async()=>{
  const x=context();x.c.empty=(title,message)=>title+message;
  x.data.tenant.id='other';await x.c.renderBillingPage();
  assert.match(x.page.innerHTML,/does not match/);assert.doesNotMatch(x.page.innerHTML,/4242/);
});

test('success has Dashboard CTA; catalog defaults remain editable assignment inputs',()=>{
  const x=context();x.data.monthly=monthlyData('active');
  assert.match(x.c.monthlyPanel(x.data),/Go to Dashboard/);
  const admin=fs.readFileSync(path.join(__dirname,'../public/pages/admin.js'),'utf8');
  assert.ok(admin.includes('value="${s.standard_price_cents/100}"'));
  assert.ok(admin.includes('options[0].standard_price_cents/100'));
});

test('client creation submits each monthly price without enhancement usage special cases',()=>{
  const admin=fs.readFileSync(path.join(__dirname,'../public/pages/admin.js'),'utf8');
  const statement=admin.slice(admin.indexOf("const services=[...root.querySelectorAll('input[name=services]:checked')]"),admin.indexOf('\n',admin.indexOf("const services=[...root.querySelectorAll('input[name=services]:checked')]")));
  const values={crm:'40',platform_core:'10',piq_enhancement:'5'};
  const root={querySelectorAll:()=>Object.keys(values).map(value=>({value})),
    querySelector:selector=>({value:values[selector.match(/="([^"]+)"/)[1]]})};
  const c={root};vm.createContext(c);
  vm.runInContext(statement+'globalThis.result=services;',c);
  assert.deepEqual(JSON.parse(JSON.stringify(c.result)),[
    {service_code:'crm',contract_price_cents:4000},{service_code:'platform_core',contract_price_cents:1000},
    {service_code:'piq_enhancement',contract_price_cents:500}]);
  values.piq_enhancement='';vm.runInContext('{'+statement+'globalThis.blank=services;}',c);
  assert.equal(c.blank[2].contract_price_cents,0);
});

test('login blocks duplicate submits and restores button on failure',async()=>{
  const app=fs.readFileSync(path.join(__dirname,'../public/app.js'),'utf8');
  const start=app.indexOf('$("#login-form").addEventListener("submit", async (event) => {');
  const end=app.indexOf('  document.querySelectorAll("[data-demo-email]")',start);
  assert.ok(start>=0 && end>start);
  let handler,reject,calls=0;const button={disabled:false,textContent:'Sign in',setAttribute(){},removeAttribute(){}};
  const form={email:{value:'x'},password:{value:'y'},querySelector:()=>button};
  const c={$:()=>({addEventListener:(_,fn)=>{handler=fn;}}),api:()=>{calls++;return new Promise((_,r)=>{reject=r;});},toast(){},enterApp(){}};
  vm.createContext(c);vm.runInContext(app.slice(start,end),c);
  const event={preventDefault(){},currentTarget:form};const pending=handler(event);
  assert.equal(button.disabled,true);assert.equal(button.textContent,'Signing in...');
  await handler(event);assert.equal(calls,1);reject(Error('bad login'));await pending;
  assert.equal(button.disabled,false);assert.equal(button.textContent,'Sign in');
});
