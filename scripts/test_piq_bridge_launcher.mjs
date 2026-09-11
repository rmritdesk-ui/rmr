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
 const x=await setup(async(path)=>{if(path.includes('availability'))return {enabled:true,mapping_id:'mapping-a'};throw Error('summary unavailable');});
 assert.equal(await x.render(),true);assert.match(x.page.innerHTML,/summary is temporarily unavailable/);assert.match(x.page.innerHTML,/data-open-prospectiq/);
});
