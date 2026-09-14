import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../public/pages/prospectiq_bridge_ui.js',import.meta.url),'utf8');
async function setup(api) {
 const state={selectedTenantId:'tenant-a',route:'piq'},calls=[];
 const context=vm.createContext({URL,encodeURIComponent,location:{assign:url=>calls.push(url)}});
 const button={disabled:false,addEventListener:(_,fn)=>{button.click=fn;}};
 const page={isConnected:true,innerHTML:'native sentinel',querySelector:()=>button};
 const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
 const deps={'../api.js':{api},'../state.js':{state},'../ui.js':{esc,toast:()=>{}}};
 const module=new vm.SourceTextModule(source,{context});
 await module.link(name=>new vm.SyntheticModule(Object.keys(deps[name]),function(){for(const [key,value]of Object.entries(deps[name]))this.setExport(key,value);},{context}));
 await module.evaluate();
 return {render:()=>module.namespace.renderProspectiqBridge(page,'tenant-a'),page,button,state,calls};
}
test('explicit bridge OFF preserves native page',async()=>{
 const x=await setup(async()=>({enabled:false}));assert.equal(await x.render(),false);assert.equal(x.page.innerHTML,'native sentinel');
});
test('bridge ON renders summary only and launches Leads',async()=>{
 const requests=[];
 const x=await setup(async(path,options)=>{
  requests.push([path,options]);
  if(path.includes('availability'))return {enabled:true,mapping_id:'mapping-a'};
  if(path.endsWith('/profiles/bootstrap'))return {status:'completed'};
  if(path.endsWith('/launch'))return {launch_url:'https://piq.localhost/#rmr-start=test'};
  return {profiles:[{id:'source-a',name:'Original <profile>',active:true,industries_json:['Mortgage'],locations_json:['Phoenix']}]};
 });
 assert.equal(await x.render(),true);assert.match(x.page.innerHTML,/Original &lt;profile>/);
 assert.match(x.page.innerHTML,/Open ProspectIQ/);
 for(const label of ['Pull Leads','Run Adaptive Research','Move to CRM','Create Target Profile','data-open-piq'])assert.ok(!x.page.innerHTML.includes(label));
 await x.button.click();assert.equal(requests.at(-1)[1].body.destination,'prospects');assert.equal(x.calls.length,1);
});
test('unavailable or unauthorized bridge fails closed, not native fallback',async()=>{
 const x=await setup(async()=>{throw Error('unavailable');});assert.equal(await x.render(),true);assert.match(x.page.innerHTML,/data-piq-bridge-unavailable/);
});
test('tenant change during loading cannot display or launch another tenant',async()=>{
 let x;x=await setup(async()=>{x.state.selectedTenantId='tenant-b';return {enabled:true,mapping_id:'mapping-a'};});
 assert.equal(await x.render(),true);assert.equal(x.page.innerHTML,'native sentinel');assert.equal(x.button.click,undefined);
});
test('profile-summary read failure still permits authorized launcher',async()=>{
 const x=await setup(async(path)=>{if(path.includes('availability'))return {enabled:true,mapping_id:'mapping-a'};if(path.endsWith('/profiles/bootstrap'))return {status:'completed'};throw Error('summary unavailable');});
 assert.equal(await x.render(),true);assert.match(x.page.innerHTML,/summary is temporarily unavailable/);assert.match(x.page.innerHTML,/data-open-prospectiq/);
});
test('first use prepares only through POST then permits the existing launch',async()=>{
 const requests=[];let x;
 x=await setup(async(path,options)=>{
  requests.push([path,options]);
  if(path.includes('availability'))return {enabled:true,status:'unprovisioned',can_provision:true};
  if(path.endsWith('/profiles/bootstrap'))return {status:'completed'};
  if(path.endsWith('/provision')){
   assert.match(x.page.innerHTML,/Preparing ProspectIQ/);
   assert.equal(options.method,'POST');assert.equal(options.body.tenant_id,'tenant-a');
   return {status:'ready',mapping_id:'new-mapping'};
  }
  if(path.endsWith('/launch'))return {launch_url:'https://piq.localhost/#rmr-start=new'};
  return {profiles:[]};
 });
 await x.render();assert.match(x.page.innerHTML,/Open ProspectIQ/);assert.ok(!x.page.innerHTML.includes('new-mapping'));
 await x.button.click();assert.equal(requests.at(-1)[1].body.mapping_id,'new-mapping');
 assert.equal(requests.filter(([p])=>p.endsWith('/provision')).length,1);
});
test('read-only first user cannot start provisioning',async()=>{
 let count=0;const x=await setup(async()=>{count++;return {enabled:true,status:'unprovisioned',can_provision:false};});
 await x.render();assert.equal(count,1);assert.match(x.page.innerHTML,/client administrator/);
});
test('preparation failure hides infrastructure errors and offers retry without native fallback',async()=>{
 let ready=false;const x=await setup(async path=>{
  if(path.includes('availability'))return {enabled:true,status:'unprovisioned',can_provision:true};
  if(path.endsWith('/profiles/bootstrap'))return {status:'completed'};
  if(path.endsWith('/provision')){if(!ready)throw Error('PRIVATE DATABASE DETAIL');return {status:'ready',mapping_id:'mapped'};}
  return {profiles:[]};
 });
 assert.equal(await x.render(),true);assert.match(x.page.innerHTML,/Retry preparation/);assert.ok(!x.page.innerHTML.includes('PRIVATE'));
 ready=true;await x.render();assert.match(x.page.innerHTML,/Open ProspectIQ/);
});
test('tenant navigation during provisioning cannot publish stale mapping or launcher',async()=>{
 let x;x=await setup(async path=>{
  if(path.includes('availability'))return {enabled:true,status:'unprovisioned',can_provision:true};
  x.state.selectedTenantId='tenant-b';return {status:'ready',mapping_id:'old-tenant'};
 });
 await x.render();assert.ok(!x.page.innerHTML.includes('Open ProspectIQ'));assert.equal(x.button.click,undefined);
});
test('bootstrap completes after provisioning and before launching; failure is actionable and retryable',async()=>{
 let complete=false;const calls=[];
 const x=await setup(async(path,options)=>{
  calls.push(path);
  if(path.includes('availability'))return {enabled:true,status:'unprovisioned',can_provision:true};
  if(path.endsWith('/provision'))return {status:'ready',mapping_id:'mapped'};
  if(path.endsWith('/profiles/bootstrap')){
   assert.equal(options.method,'POST');assert.equal(options.body.tenant_id,'tenant-a');
   if(!complete)throw Error('PRIVATE SQL ERROR');return {status:'completed'};
  }
  return {profiles:[]};
 });
 await x.render();assert.match(x.page.innerHTML,/Retry preparation/);assert.ok(!x.page.innerHTML.includes('PRIVATE'));
 assert.ok(!x.page.innerHTML.includes('data-open-prospectiq'));
 complete=true;await x.render();assert.match(x.page.innerHTML,/data-open-prospectiq/);
 assert.ok(calls.findIndex(p=>p.endsWith('/provision'))<calls.findIndex(p=>p.endsWith('/profiles/bootstrap')));
});
test('tenant switch during bootstrap cannot render stale launcher',async()=>{
 let x;x=await setup(async path=>{
  if(path.includes('availability'))return {enabled:true,mapping_id:'mapped'};
  x.state.selectedTenantId='tenant-b';return {status:'completed'};
 });
 await x.render();assert.ok(!x.page.innerHTML.includes('data-open-prospectiq'));
});
