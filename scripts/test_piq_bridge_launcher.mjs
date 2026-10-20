import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
const source=readFileSync(new URL('../public/pages/prospectiq_bridge_ui.js',import.meta.url),'utf8');
async function setup(api) {
 const state={selectedTenantId:'tenant-a',route:'piq'},calls=[];
 const storage=new Map(),nodes=new Map(),messages=[];
 const context=vm.createContext({URL,encodeURIComponent,Set,crypto:{randomUUID},confirm:()=>true,
   localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},location:{assign:url=>calls.push(url)}});
 const node=selector=>{
  if(!nodes.has(selector)){
   const n={disabled:false,innerHTML:'',dataset:{},addEventListener:(_,fn)=>{n.click=fn;},querySelector:s=>node(s),
    querySelectorAll:()=>[...n.innerHTML.matchAll(/data-copy-profile="([^"]+)"/g)].map(m=>{const b=node('[data-copy-profile="'+m[1]+'"]');b.dataset.copyProfile=m[1];return b;})};
   nodes.set(selector,n);
  }return nodes.get(selector);
 };
 const button=node('[data-open-prospectiq]');
 const page={isConnected:true,innerHTML:'native sentinel',querySelector:node};
 const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
 const deps={'../api.js':{api},'../state.js':{state},'../ui.js':{esc,toast:m=>messages.push(m)}};
 const module=new vm.SourceTextModule(source,{context});
 await module.link(name=>new vm.SyntheticModule(Object.keys(deps[name]),function(){for(const [key,value]of Object.entries(deps[name]))this.setExport(key,value);},{context}));
 await module.evaluate();
 return {render:()=>module.namespace.renderProspectiqBridge(page,'tenant-a'),page,button,state,calls,node,storage,messages};
}
test('explicit bridge OFF preserves native page',async()=>{
 const x=await setup(async()=>({enabled:false}));assert.equal(await x.render(),false);assert.equal(x.page.innerHTML,'native sentinel');
});
test('bridge ON shows only the launcher without historical profile controls or requests',async()=>{
 const requests=[];
 const x=await setup(async(path,options)=>{
  requests.push([path,options]);
  if(path.includes('availability'))return {enabled:true,mapping_id:'mapping-a'};
  if(path.endsWith('/profiles/bootstrap'))return {status:'completed'};
  if(path.endsWith('/launch'))return {launch_url:'https://piq.localhost/#rmr-start=test'};
  return {profiles:[{id:'source-a',name:'Original <profile>',active:true,industries_json:['Mortgage'],locations_json:['Phoenix']}]};
 });
 assert.equal(await x.render(),true);assert.ok(!x.page.innerHTML.includes('Original'));
 assert.match(x.page.innerHTML,/Open ProspectIQ/);
 for(const label of ['Pull Leads','Run Adaptive Research','Move to CRM','Create Target Profile','data-open-piq',
   'Previous RMR Profiles','data-piq-history','data-piq-source-profile','data-copy-profile'])assert.ok(!x.page.innerHTML.includes(label));
 assert.equal(x.node('[data-piq-history]').click,undefined);
 assert.equal(requests.length,2);
 await x.button.click();assert.equal(requests.at(-1)[1].body.destination,'prospects');assert.equal(x.calls.length,1);
 assert.ok(requests.every(([path])=>!path.includes('target-profiles')&&!path.includes('history-copy')));
});
test('unavailable or unauthorized bridge fails closed, not native fallback',async()=>{
 const x=await setup(async()=>{throw Error('unavailable');});assert.equal(await x.render(),true);assert.match(x.page.innerHTML,/data-piq-bridge-unavailable/);
});
test('tenant change during loading cannot display or launch another tenant',async()=>{
 let x;x=await setup(async()=>{x.state.selectedTenantId='tenant-b';return {enabled:true,mapping_id:'mapping-a'};});
 assert.equal(await x.render(),true);assert.equal(x.page.innerHTML,'native sentinel');assert.equal(x.button.click,undefined);
});
test('historical profile API is not needed for the authorized launcher',async()=>{
 const x=await setup(async(path)=>{if(path.includes('availability'))return {enabled:true,mapping_id:'mapping-a'};if(path.endsWith('/profiles/bootstrap'))return {status:'completed'};throw Error('summary unavailable');});
 assert.equal(await x.render(),true);assert.match(x.page.innerHTML,/data-open-prospectiq/);
 assert.ok(!x.page.innerHTML.includes('data-piq-history-content'));
});

test('Open ProspectIQ prevents duplicate launch and preserves the secure destination',async()=>{
 const requests=[];let release;
 const x=await setup(async(path,options)=>{
  if(path.includes('availability'))return {enabled:true,mapping_id:'mapped'};
  if(path.endsWith('/profiles/bootstrap'))return {status:'completed'};
  if(path.endsWith('/launch')){
   requests.push(options.body);
   await new Promise(r=>release=r);
   return {launch_url:'https://piq.test/#rmr-start=existing-flow'};
  }
  throw Error('Unexpected history request');
 });
 await x.render();assert.equal(requests.length,0);
 const first=x.button.click();await new Promise(r=>setImmediate(r));
 await x.button.click();assert.equal(requests.length,1);
 assert.equal(requests[0].mapping_id,'mapped');assert.equal(requests[0].destination,'prospects');
 release();await first;assert.equal(x.calls[0],'https://piq.test/#rmr-start=existing-flow');
});
test('insecure launch URL is rejected and button becomes retryable',async()=>{
 const x=await setup(async path=>{
  if(path.includes('availability'))return {enabled:true,mapping_id:'mapped'};
  if(path.endsWith('/profiles/bootstrap'))return {status:'completed'};
  return {launch_url:'http://piq.test/'};
 });
 await x.render();await x.button.click();
 assert.equal(x.calls.length,0);assert.equal(x.button.disabled,false);
 assert.match(x.messages[0],/Secure ProspectIQ destination required/);
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
